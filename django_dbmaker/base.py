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


# Copyright (c) 2008, django-dbmaker developers (see README.rst).
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

"""
DBMaker database backend for Django.

Requires pyodbc: https://github.com/mkleehammer/pyodbc/
"""
import datetime
import logging
import os
import re
import sys
from time import time
import warnings

from django.core.exceptions import ImproperlyConfigured

try:
    import pyodbc as Database
except ImportError:
    e = sys.exc_info()[1]
    raise ImproperlyConfigured("Error loading pyodbc module: %s" % e)

m = re.match(r'(\d+)\.(\d+)\.(\d+)(?:-beta(\d+))?', Database.version)
vlist = list(m.groups())
if vlist[3] is None: vlist[3] = '9999'
pyodbc_ver = tuple(map(int, vlist))
if pyodbc_ver < (2, 0, 38, 9999):
    raise ImproperlyConfigured("pyodbc 2.0.38 or newer is required; you have %s" % Database.version)

from django.db import utils
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.validation import BaseDatabaseValidation
from django.conf import settings
from django.utils.asyncio import async_unsafe

from .client import DatabaseClient
from .creation import DatabaseCreation
from .features import DatabaseFeatures
from .introspection import DatabaseIntrospection
from .operations import DatabaseOperations
from .schema import DatabaseSchemaEditor

DatabaseError = Database.Error
IntegrityError = Database.IntegrityError

class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'dbmaker'
    display_name = 'dbmaker'
    Database = Database

    # Collations:       http://msdn2.microsoft.com/en-us/library/ms184391.aspx
    #                   http://msdn2.microsoft.com/en-us/library/ms179886.aspx
    # T-SQL LIKE:       http://msdn2.microsoft.com/en-us/library/ms179859.aspx
    # Full-Text search: http://msdn2.microsoft.com/en-us/library/ms142571.aspx
    #   CONTAINS:       http://msdn2.microsoft.com/en-us/library/ms187787.aspx
    #   FREETEXT:       http://msdn2.microsoft.com/en-us/library/ms176078.aspx
    data_types = {
        'AutoField':                    'serial',
        'BigAutoField':                 'bigserial',
        'BinaryField':                  'blob',
        'BooleanField':                 'int',
        'CharField':                    'nvarchar(%(max_length)s)',
        'DateField':                    'date',
        'DateTimeField':                'timestamp',
        'DecimalField':                 'decimal(%(max_digits)s, %(decimal_places)s)',
        'DurationField':                'bigint',
        'FileField':                    'nvarchar(%(max_length)s)',
        'FilePathField':                'nvarchar(%(max_length)s)',
        'FloatField':                   'double',
        'IntegerField':                 'int',
        'JSONField':                    'jsoncols',
        'BigIntegerField':              'bigint',
        'IPAddressField':               'nvarchar(15)',
        'GenericIPAddressField':        'nvarchar(39)',
        'OneToOneField':                'int',
        'PositiveBigIntegerField':      'bigint',
        'PositiveIntegerField':         'int',
        'PositiveSmallIntegerField':    'smallint',
        'SlugField':                    'nvarchar(%(max_length)s)',
        'SmallAutoField':               'serial',
        'SmallIntegerField':            'smallint',
        'TextField':                    'nclob',
        'TimeField':                    'time',
        'UUIDField':                    'varchar(36)',       
    }

    data_type_check_constraints = {
        'PositiveBigIntegerField': '"%(column)s" >= 0',
        'PositiveIntegerField': '"%(column)s" >= 0',
        'PositiveSmallIntegerField': '"%(column)s" >= 0',
    }

    _limited_data_types = (
       'file', 'jsoncols',
    )
    operators = {
        # Since '=' is used not only for string comparision there is no way
        # to make it case (in)sensitive. It will simply fallback to the
        # database collation.
        'exact': '= %s',
        'iexact': '= upper(%s)',
        #'iexact': "= (%s)",
        'contains': "LIKE %s ESCAPE '\\'",
        'icontains': "LIKE %s ESCAPE '\\'",
        #'icontains': "LIKE UPPER(%s) ESCAPE '\\'",
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': "LIKE %s ESCAPE '\\'",
        'endswith': "LIKE %s ESCAPE '\\'",
        'istartswith': "LIKE %s ESCAPE '\\'",
        'iendswith': "LIKE %s ESCAPE '\\'",
        #'istartswith': "LIKE UPPER(%s) ESCAPE '\\'",
        #'iendswith': "LIKE UPPER(%s) ESCAPE '\\'",

        # TODO: remove, keep native T-SQL LIKE wildcards support
        # or use a "compatibility layer" and replace '*' with '%'
        # and '.' with '_'
        'regex': 'LIKE %s',
        'iregex': 'LIKE %s',

        # TODO: freetext, full-text contains...
    }

    pattern_esc = r"REPLACE(REPLACE(REPLACE({}, '\', '\\'), '%%', '\%%'), '_', '\_')"
    pattern_ops = {
        'contains': r"LIKE '%%' || {} || '%%' ESCAPE '\'",
        'icontains': r"LIKE '%%' || {} || '%%' ESCAPE '\'",
        #'icontains': r"LIKE '%%' || UPPER({}) || '%%' ESCAPE '\'",
        'startswith': r"LIKE {} || '%%' ESCAPE '\'",
        'istartswith': r"LIKE {} || '%%' ESCAPE '\'",
        #'istartswith': r"LIKE UPPER({}) || '%%' ESCAPE '\'",
        'endswith': r"LIKE '%%' || {} ESCAPE '\'",
        'iendswith': r"LIKE '%%' || {} ESCAPE '\'",
        #'iendswith': r"LIKE '%%' || UPPER({}) ESCAPE '\'",
    }

    # In Django 1.8 data_types was moved from DatabaseCreation to DatabaseWrapper.
    # See https://docs.djangoproject.com/en/1.10/releases/1.8/#database-backend-api
    SchemaEditorClass = DatabaseSchemaEditor
    features_class = DatabaseFeatures
    ops_class = DatabaseOperations
    client_class = DatabaseClient
    creation_class = DatabaseCreation
    introspection_class = DatabaseIntrospection
    validation_class = BaseDatabaseValidation  
    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)
        self.test_create = self.settings_dict.get('TEST_CREATE', True)

    def get_connection_params(self):
        settings_dict = self.settings_dict
        # None may be used to connect to the default 'dbsample5' db
        if settings_dict['NAME'] == '':
            raise ImproperlyConfigured(
                "settings.DATABASES is improperly configured. "
                "Please supply the NAME value.")
        if len(settings_dict['NAME'] or '') > self.ops.max_name_length():
            raise ImproperlyConfigured(
                "The database name '%s' (%d characters) is longer than "
                "limit of %d characters. Supply a shorter NAME "
                "in settings.DATABASES." % (
                    settings_dict['NAME'],
                    len(settings_dict['NAME']),
                    self.ops.max_name_length(),
                )
            )
        conn_params = {
            'database': settings_dict['NAME'] or 'dbsample5',
            #**settings_dict['OPTIONS'],
        }
        conn_params.update(settings_dict['OPTIONS'])

        if settings_dict['USER']:
            conn_params['user'] = settings_dict['USER']
        if settings_dict['PASSWORD']:
            conn_params['password'] = settings_dict['PASSWORD']
        if settings_dict['HOST']:
            conn_params['host'] = settings_dict['HOST']
        if settings_dict['PORT']:
            conn_params['port'] = settings_dict['PORT']
        return conn_params
    
    @async_unsafe
    def get_new_connection(self, conn_params):
        connection = Database.connect(**conn_params)
        return connection

    def init_connection_state(self):
        cursor = self.create_cursor()
        cursor.execute("set string concat on")
        cursor.execute("set free catalog cache on")
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute("set itcmd on")
        options = self.settings_dict["OPTIONS"].copy()
        if 'SELTMPBB' in options:
           seltmpbb=options['SELTMPBB']
           if(seltmpbb == True):
              cursor.execute("call SETSYSTEMOPTION(\'SELTMPBB\', \'1\')")
              cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cursor.close()
        if not self.get_autocommit():
            self.commit()

    def _set_autocommit(self, autocommit):
        with self.wrap_database_errors:
            self.connection.autocommit = autocommit

    def create_cursor(self, name=None):
        return CursorWrapper(self.connection.cursor(), self)

    def check_constraints(self, table_names=None):
        """
        Check constraints by setting them to immediate. Return them to deferred
        afterward.
        """
        with self.cursor() as cursor:
            self.cursor().execute('CALL SETSYSTEMOPTION(\'FKCHK\', \'1\');')
            self.cursor().execute('CALL SETSYSTEMOPTION(\'FKCHK\', \'0\');')
         
    def disable_constraint_checking(self):
        with self.cursor() as cursor:
            cursor.execute("CALL SETSYSTEMOPTION(\'FKCHK\', \'0\');")
        return True
               
    def enable_constraint_checking(self):
        with self.cursor() as cursor:
            cursor.execute('CALL SETSYSTEMOPTION(\'FKCHK\', \'1\');')
    
    def is_usable(self):
        try:
            # Use a psycopg cursor directly, bypassing Django's utilities.
            self.connection.cursor().execute("SELECT 1")
        except Database.Error:
            return False
        else:
            return True    


class CursorWrapper(object):
    """
    A wrapper around the pyodbc's cursor that takes in account a) some pyodbc
    DB-API 2.0 implementation and b) some common ODBC driver particularities.
    """
    def __init__(self, cursor, connection):
        self.cursor = cursor
        self.connection = connection
        self.last_sql = ''
        self.last_params = ()

    def close(self):
        try:
            self.cursor.close()
        except Database.ProgrammingError:
            pass

    def format_sql(self, sql, n_params=None):
        # pyodbc uses '?' instead of '%s' as parameter placeholder.
        if n_params is not None:
            try:
                if '%s' in sql and n_params>0:
                    sql = sql.replace('%s', '?')
                else:
                    sql = sql % tuple('?' * n_params)
            except Exception as e:
                #Todo checkout whats happening here
                pass
        else:
            if '%s' in sql:
                sql = sql.replace('%s', '?')
        return sql

    def format_params(self, params):
        fp = []
        for p in params:
            if isinstance(p, type(True)):
                if p:
                    fp.append(1)
                else:
                    fp.append(0)
            else:
                fp.append(p)
        return tuple(fp)
    
    def quote_value(self, value):
        if isinstance(value, (datetime.date, datetime.time, datetime.datetime)):
            return "cast('%s' as timestamp)" % value
        elif isinstance(value, str):
            return "'%s'" % value.replace("\'", "\'\'")
        elif isinstance(value, (bytes, bytearray, memoryview)):
            return  "X'%s'" % value.hex()
        elif isinstance(value, bool):
            return "1" if value else "0"
        elif value is None:
            return "NULL"
        else:
            return str(value)

    def execute(self, sql, params=()):       
        self.last_sql = sql
        if (('CASE WHEN' in sql) or
             ( '(%s) AS' in sql) or
             ('LIKE %s' in sql) or
             ('GROUP BY' in sql) or
             ('COALESCE(' in sql)) and params is not None:
            sql = sql % tuple(map(self.quote_value, params))
            try:
               return self.cursor.execute(sql)
            except (IntegrityError, DatabaseError) as e:
               esg = e.args[1]
               logger = logging.getLogger('django.db.backends')
               logger.error('DEBUG SQL')
               logger.error("----------------------------------------------------------------------------")
               logger.error(
                '%s \n SQL: %s', esg, sql)
               e = sys.exc_info()[1]
               if '[23000]' in esg:
                  raise utils.IntegrityError(*e.args)
               else:
                  raise utils.DatabaseError(*e.args)
        else:
            sql = self.format_sql(sql, len(params))
            params = self.format_params(params)
            self.last_params = params
            sql = sql.replace('%%', '%')
        try:
           return self.cursor.execute(sql, params)
        except (IntegrityError, DatabaseError) as e:
            esg = e.args[1]
            logger = logging.getLogger('django.db.backends')
            logger.error('DEBUG SQL')
            logger.error("----------------------------------------------------------------------------")
            logger.error(
                '%s \n SQL: %s', esg, sql)
            logger.error(params)
            e = sys.exc_info()[1]
            if '[23000]' in esg:
                raise utils.IntegrityError(*e.args)
            else:
                raise utils.DatabaseError(*e.args)
        
    def executemany(self, sql, params_list):
        sql = self.format_sql(sql)
        # pyodbc's cursor.executemany() doesn't support an empty param_list
        if not params_list:
            if '?' in sql:
                return
        else:
            raw_pll = params_list
            params_list = [self.format_params(p) for p in raw_pll]

        try:
            return self.cursor.executemany(sql, params_list)
        except IntegrityError:
            e = sys.exc_info()[1]
            raise utils.IntegrityError(*e.args)
        except DatabaseError:
            e = sys.exc_info()[1]
            raise utils.DatabaseError(*e.args)
    
    def format_results(self, rows):
        """
        Decode data coming from the database if needed and convert rows to tuples
        (pyodbc Rows are not sliceable).
        """
        needs_utc = settings.USE_TZ
        if not (needs_utc):
            return tuple(rows)
        # FreeTDS (and other ODBC drivers?) don't support Unicode yet, so we
        # need to decode UTF-8 data coming from the DB
        fr = []
        for row in rows:
            if needs_utc and isinstance(row, datetime.datetime):
                row = row.replace(tzinfo=datetime.timezone.utc)
            fr.append(row)
        return tuple(fr)

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            return self.format_results(row)
        return []

    def fetchmany(self, chunk):
        return [self.format_results(row) for row in self.cursor.fetchmany(chunk)]

    def fetchall(self):
        return [self.format_results(row) for row in self.cursor.fetchall()]

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        return getattr(self.cursor, attr)

    def __iter__(self):
        return iter(self.cursor)


    # # DBMaker doesn't support explicit savepoint commits; savepoints are
    # # implicitly committed with the transaction.
    # # Ignore them.
    def savepoint_commit(self, sid):
        # if something is populating self.queries, include a fake entry to avoid
        # issues with tests that use assertNumQueries.
        if self.queries:
            self.queries.append({
                'sql': '-- RELEASE SAVEPOINT %s -- (because assertNumQueries)' % self.ops.quote_name(sid),
                'time': '0.000',
            })

    def _savepoint_allowed(self):
        return self.in_atomic_block
    
