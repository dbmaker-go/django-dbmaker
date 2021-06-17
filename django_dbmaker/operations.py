# Copyright 2013-2017 Lionheart Software LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Copyright (c) 2008, django-pyodbc developers (see README.rst).
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.
#
#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
#
#     3. Neither the name of django-sql-server nor the names of its contributors
#        may be used to endorse or promote products derived from this software
#        without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import datetime
import decimal
import time
import uuid
from _decimal import Decimal
from django.db.models.fields import AutoField, IntegerField, DateTimeField,\
    BooleanField

try:
    import pytz
except:
    pytz = None

from django.conf import settings
from django.db.backends.base.operations import BaseDatabaseOperations
from django.db import utils
from django.utils.dateparse import parse_date, parse_time, parse_datetime
from django.db.models import Exists, ExpressionWrapper
from django.db.models.expressions import RawSQL
from django.db.models.sql.where import WhereNode

#from django_dbmaker.compat import smart_text, string_types, timezone
#from django.utils import six
from django.utils import timezone
from django.utils.duration import duration_microseconds

class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = "django_dbmaker.compiler"
        
    cast_char_field_without_max_length = 'NVARCHAR2(256)'
    cast_data_types = {
        'AutoField': 'INT',
        'BigAutoField': 'BIGINT',
        'TextField': cast_char_field_without_max_length,
    }
    def __init__(self, connection):
        super(DatabaseOperations, self).__init__(connection) 
        self.connection = connection
        self._left_sql_quote = None
        self._right_sql_quote = None

    @property
    def left_sql_quote(self):
        if self._left_sql_quote is None:
            options = self.connection.settings_dict.get('OPTIONS', {})
            q = options.get('left_sql_quote', None)
            if q is not None:
                self._left_sql_quote = q
            else:
                self._left_sql_quote = '"'
        return self._left_sql_quote

    @property
    def right_sql_quote(self):
        if self._right_sql_quote is None:
            options = self.connection.settings_dict.get('OPTIONS', {})
            q = options.get('right_sql_quote', None)
            if q is not None:
                self._right_sql_quote = q
            else:           
                self._right_sql_quote = '"'
        return self._right_sql_quote
        
    def conditional_expression_supported_in_where_clause(self, expression):
        if isinstance(expression, (Exists, WhereNode)):
            return True
        if isinstance(expression, ExpressionWrapper) and expression.conditional:
            return self.conditional_expression_supported_in_where_clause(expression.expression)
        if isinstance(expression, RawSQL) and expression.conditional:
            return True
        return False
    
    def combine_expression(self, connector, sub_expressions):
        """
        DBMaker requires special cases for some operators in query expressions
        """
        lhs, rhs = sub_expressions
        if connector == '%%':
            return 'MOD(%s)' % ','.join(sub_expressions)
        elif connector == '&':
            return 'BAND(%s)' % ','.join(sub_expressions)
        elif connector == '|':
            return 'BOR(%s)' % ','.join(sub_expressions)
        elif connector == '^':
            return 'POWER(%s)' % ','.join(sub_expressions)
        elif connector == '<<':
            return '(%(lhs)s * POWER(2, %(rhs)s))' % {'lhs': lhs, 'rhs': rhs}
        elif connector == '>>':
            return 'FLOOR(%(lhs)s / POWER(2, %(rhs)s))' % {'lhs': lhs, 'rhs': rhs}
        elif connector == '#':
            return 'BXOR(%s)' % ','.join(sub_expressions)
        return super().combine_expression(connector, sub_expressions)
    
    def combine_duration_expression(self, connector, sub_expressions):
        lhs, rhs = sub_expressions
        sign = ' * -1' if connector == '-' else ''
        if lhs.startswith('TIMESTAMPADD'):
            col, sql = rhs, lhs
        else:
            col, sql = lhs, rhs
        params = [sign for _ in range(sql.count('TIMESTAMPADD'))]
        params.append(col)
        return sql % tuple(params)

    def date_extract_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month', 'day' or 'week_day', returns
        the SQL that extracts a value from the given date field field_name.
        """
        if lookup_type == 'week_day':
            # DAYOFWEEK() returns an integer, 1-7, Sunday=1.
            # Note: WEEKDAY() returns 0-6, Monday=0.
            return "DAYOFWEEK(%s)" % field_name
        elif lookup_type == 'week':
            return "WEEK(%s)" % field_name
        elif lookup_type == 'quarter':
            return "QUARTER(%s)" % field_name
        elif lookup_type == 'month':
            return "MONTH(%s)" % field_name
        elif lookup_type == 'day':
            return "DAYOFMONTH(%s)" % field_name
        elif lookup_type == 'hour':
            return "HOUR(%s)" % field_name
        elif lookup_type == 'minute':
            return "MINUTE(%s)" % field_name
        else:
            return "SECOND(%s)" % field_name
    
    def date_interval_sql(self, timedelta):
        """
        implements the interval functionality for expressions
        """
        sec = timedelta.seconds + timedelta.days * 86400
        sql = 'TIMESTAMPADD(\'s\', %d%%s, %%s)' % sec
        if timedelta.microseconds:
            sql = 'TIMESTAMPADD(\'f\', %d%%s, %s)' % (timedelta.microseconds, sql)
        return sql
     
    def date_trunc_sql(self, lookup_type, field_name, tzname=None):
        if lookup_type =='year':
            return "TO_DATE(STRDATE(%s,'start of year'), 'yyyy-mm-dd')" % field_name
        if lookup_type == 'month':
            return "TO_DATE(STRDATE(%s, 'start of month'), 'yyyy-mm-dd')" % field_name
        elif lookup_type == 'quarter':
            return "MDY(YEAR(%s), (QUARTER(%s)-1)*3+1, 1)" % (field_name , field_name)
        elif lookup_type == 'week':
            return "TO_DATE(STRDATE(%s, 'start of week'), 'yyyy-mm-dd')" % field_name
        else:
            return field_name
        #return "DATEADD(%s, DATEDIFF(%s, 0, %s), 0)" % (lookup_type, lookup_type, field_name)

    def format_for_duration_arithmetic(self, sql):
        if sql == '%s':
            # use DATEADD only once because Django prepares only one parameter for this 
            fmt = 'TIMESTAMPADD(\'s\', %s / 1000000%%s, %%s)'
            sql = '%%s'
        else:
            # use DATEADD twice to avoid arithmetic overflow for number part
            fmt = 'TIMESTAMPADD(\'s\', %s / 1000000%%s, %%s)'
            #fmt = 'TIMESTAMPADD(\'s\', %s / 1000000%%s, TIMESTAMPADD(\'f\', %s %%%%%%%% 1000000%%s, %%s))'
            sql = (sql)  
        return fmt % sql
    
    def _convert_field_to_tz(self, field_name, tzname):
        if settings.USE_TZ and not tzname == 'UTC':
            offset = self._get_utcoffset(tzname)
            field_name = 'TIMESTAMPADD(%s, %d, %s)' % ('s', offset, field_name)
        return field_name

    def _get_utcoffset(self, tzname):
        """
        Returns UTC offset for given time zone in seconds
        """
        # SQL Server has no built-in support for tz database
        # see http://blogs.msdn.com/b/sqlprogrammability/archive/2008/03/18/using-time-zone-data-in-sql-server-2008.aspx
        zone = pytz.timezone(tzname)
        # no way to take DST into account at this point
        now = datetime.datetime.now()
        delta = zone.localize(now, is_dst=False).utcoffset()
        return delta.days * 86400 + delta.seconds

    def datetime_extract_sql(self, lookup_type, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        return self.date_extract_sql(lookup_type, field_name)
    
    def datetime_cast_date_sql(self, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        return 'DATEPART(%s)' % field_name
    
    def datetime_cast_time_sql(self, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        return "CAST(%s AS TIME)" % field_name
    
    def datetime_trunc_sql(self, lookup_type, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        fields = ['year', 'month', 'day', 'hour', 'minute', 'week']
        if lookup_type == 'quarter':
            return (
                "CAST(MDY((QUARTER({field_name})-1)*3+1, 1, YEAR({field_name})) AS TIMESTAMP)"
            ).format(field_name=field_name)
        if lookup_type == 'second':
            return field_name
        try:
            i = fields.index(lookup_type)
        except ValueError:
            sql = field_name
        else:
            sql = "CAST(STRDATETIME(%s, 'start of %s') AS TIMESTAMP)" % (field_name, fields[i])
        return sql
    
    def time_trunc_sql(self, lookup_type, field_name):
        fields = ['hour', 'minute']
        if lookup_type in fields:
            format_str = fields[lookup_type]
            return "CAST(STRTIME(%s, 'start of %s') AS TIME)" % (field_name, format_str)
        else:
            return "CAST(STRTIME(%s) AS TIME)" % (field_name)
    
    def lookup_cast(self, lookup_type, internal_type=None):
        lookup = '%s'

        # Cast text lookups to text to allow things like filter(x__contains=4)
        if lookup_type in ('iexact', 'contains', 'icontains', 'startswith',
                           'istartswith', 'endswith', 'iendswith', 'regex', 'iregex'):
            if internal_type in ('AutoField', 'IntegerField', 'DateTimeField', 'BooleanField'):
                lookup = "CAST(%s AS VARCHAR(32))"

        #  DBMaker not support Upper() like so ignore it
        #if lookup_type in ('iexact', 'icontains', 'istartswith', 'iendswith'):
            #lookup = 'UPPER(%s)' % lookup

        return lookup

    def field_cast_sql(self, db_type, internal_type=None):
        """
        Given a column type (e.g. 'BLOB', 'VARCHAR'), returns the SQL necessary
        to cast it before using it in a WHERE statement. Note that the
        resulting string should contain a '%s' placeholder for the column being
        searched against.

        TODO: verify that db_type and internal_type do not affect T-SQL CAST statement
        """
        if db_type and db_type.lower() == 'blob':
            return 'CAST(%s as nvarchar)'
        return '%s'

    def last_insert_id(self, cursor, table_name, pk_name):
#         table_name = self.quote_name(table_name)
#         cursor.execute("SELECT CAST(IDENT_CURRENT(%s) as bigint)", [table_name])
#         return cursor.fetchone()[0]
        table_name = self.quote_name(table_name)
        cursor.execute(" select LAST_SERIAL from SYSCONINFO")
#         cursor.execute("SELECT cast(count(*) as bigint) from %s" % table_name)
        return cursor.fetchone()[0]
     
    def fetch_returned_insert_id(self, cursor):
        """
        Given a cursor object that has just performed an INSERT/OUTPUT statement
        into a table that has an auto-incrementing ID, returns the newly created
        ID.
        """
        return cursor.fetchone()[0]

    def max_name_length(self):
        return 128

    def quote_name(self, name):
        """
        Returns a quoted version of the given table, index or column name. Does
        not quote the given name if it's already been quoted.
        """
        if name.startswith(self.left_sql_quote) and name.endswith(self.right_sql_quote):
            return name # Quoting once is enough.
        return '%s%s%s' % (self.left_sql_quote, name, self.right_sql_quote)

    def random_function_sql(self):
        """
        Returns a SQL expression that returns a random value.
        """
        return "RAND()"

    def last_executed_query(self, cursor, sql, params):
        """
        Returns a string of the query last executed by the given cursor, with
        placeholders replaced with actual values.

        `sql` is the raw query containing placeholders, and `params` is the
        sequence of parameters. These are used by default, but this method
        exists for database backends to provide a better implementation
        according to their own quoting schemes.
        """
        return super(DatabaseOperations, self).last_executed_query(cursor, cursor.last_sql, cursor.last_params)

    def bulk_insert_sql(self, fields, placeholder_rows):
        placeholder_rows_sql = (", ".join(row) for row in placeholder_rows)
        values_sql = ", ".join("(%s)" % sql for sql in placeholder_rows_sql)
        return "VALUES " + values_sql

    def savepoint_commit_sql(self, sid):
       """
       Returns the SQL for committing the given savepoint.
       """
       return "REMOVE SAVEPOINT %s" % self.quote_name(sid)

    def sql_flush(self, style, tables, *, reset_sequences=False, allow_cascade=False):
        """
        Returns a list of SQL statements required to remove all data from
        the given database tables (without actually removing the tables
        themselves).

        The `style` argument is a Style object as returned by either
        color_style() or no_style() in django.core.management.color.
        """
        if tables:
            sql = ['CALL SETSYSTEMOPTION(\'FKCHK\', \'0\');']
            for table in tables:
                sql.append('%s %s;' % (
                    style.SQL_KEYWORD('DELETE FROM '),
                    style.SQL_FIELD(self.quote_name(table)),
                ))
            sql.append('CALL SETSYSTEMOPTION(\'FKCHK\', \'1\');')
            return sql
        else:
            return []

    #def sequence_reset_sql(self, style, model_list):
    #    """
    #    Returns a list of the SQL statements required to reset sequences for
    #    the given models.
    #
    #    The `style` argument is a Style object as returned by either
    #    color_style() or no_style() in django.core.management.color.
    #    """
    #    from django.db import models
    #    output = []
    #    for model in model_list:
    #        for f in model._meta.local_fields:
    #            if isinstance(f, models.AutoField):
    #                output.append(...)
    #                break # Only one AutoField is allowed per model, so don't bother continuing.
    #        for f in model._meta.many_to_many:
    #            output.append(...)
    #    return output

    def start_transaction_sql(self):
        """
        Returns the SQL statement required to start a transaction.
        """
        return "BEGIN TRANSACTION"

    def sql_for_tablespace(self, tablespace, inline=False):
        """
        Returns the SQL that will be appended to tables or rows to define
        a tablespace. Returns '' if the backend doesn't use tablespaces.
        """
        return "ON %s" % self.quote_name(tablespace)

    def prep_for_like_query(self, x):
        """Prepares a value for use in a LIKE query."""
        # http://msdn2.microsoft.com/en-us/library/ms179859.aspx
        return str(x).replace('%', '\%').replace('_', '\_')

    def prep_for_iexact_query(self, x):
        """
        Same as prep_for_like_query(), but called for "iexact" matches, which
        need not necessarily be implemented using "LIKE" in the backend.
        """
        return x
    
    def adapt_datetimefield_value(self, value):	
        """
        Transform a datetime value to an object compatible with what is expected
        by the backend driver for datetime columns.
        """
        if value is None:
            return None
         # Expression values are adapted by the database.
        if hasattr(value, 'resolve_expression'):
            return value
        
        if settings.USE_TZ and timezone.is_aware(value):
            # pyodbc donesn't support datetimeoffset
            value = value.astimezone(self.connection.timezone).replace(tzinfo=None)
        
        return value

    def adapt_timefield_value(self, value):
        """
        Transform a time value to an object compatible with what is expected
        by the backend driver for time columns.
        """
        if value is None:
            return None
        
        # Expression values are adapted by the database.
        if hasattr(value, 'resolve_expression'):
            return value
        # SQL Server doesn't support microseconds
        if isinstance(value, str):
            return datetime.datetime(*(time.strptime(value, '%H:%M:%S')[:6]))
        if timezone.is_aware(value):
            raise ValueError("DBMaker backend does not support timezone-aware times.")
        return datetime.time(value.hour, value.minute, value.second)

    def adapt_decimalfield_value(self, value, max_digits=None, decimal_places=None):
        return value
    
    def year_lookup_bounds(self, value):
        """
        Returns a two-elements list with the lower and upper bound to be used
        with a BETWEEN operator to query a field value using a year lookup

        `value` is an int, containing the looked-up year.
        """
        first = '%s-01-01 00:00:00'
        # SQL Server doesn't support microseconds
        last = '%s-12-31 23:59:59'
        return [first % value, last % value]
   
    def get_db_converters(self, expression):
        converters = super().get_db_converters(expression)
        internal_type = expression.output_field.get_internal_type()       
        #if internal_type == 'IntegerField':
            #converters.append(self.convert_intfield_value)
        if internal_type == 'FloatField':
            converters.append(self.convert_floatfield_value)
        elif internal_type == 'UUIDField':
            converters.append(self.convert_uuidfield_value)
        elif internal_type in ['BooleanField', 'NullBooleanField']:
            converters.append(self.convert_booleanfield_value)
        return converters
    
    def convert_booleanfield_value(self, value, expression, connection):
        if value in (0, 1):
            value = bool(value)
        return value

    def convert_intfield_value(self, value, expression, connection):
        if value is not None:
            value = int(value)
        return value
    
    def convert_floatfield_value(self, value, expression, connection):
        if value is not None:
            value = float(value)
        return value

    def convert_uuidfield_value(self, value, expression, connection):
        if value is not None:
            value = uuid.UUID(value)
        return value
    

    
    def no_limit_value(self):
        return None