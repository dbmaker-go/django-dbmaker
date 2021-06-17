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

"""
MS SQL Server database backend for Django.
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

#logger = logging.getLogger('django.db.backends')
#logger.setLevel(logging.DEBUG)
#handler = logging.FileHandler('mylog.log')
#formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#handler.setFormatter(formatter)
#logger.addHandler(handler)
#logger.debug('This is a DEBUG message')

m = re.match(r'(\d+)\.(\d+)\.(\d+)(?:-beta(\d+))?', Database.version)
vlist = list(m.groups())
if vlist[3] is None: vlist[3] = '9999'
pyodbc_ver = tuple(map(int, vlist))
if pyodbc_ver < (2, 0, 38, 9999):
    raise ImproperlyConfigured("pyodbc 2.0.38 or newer is required; you have %s" % Database.version)

from django.db import utils
try:
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.backends.base.validation import BaseDatabaseValidation
except ImportError:
    # import location prior to Django 1.8
    from django.db.backends import BaseDatabaseWrapper, BaseDatabaseFeatures, BaseDatabaseValidation
from django.db.backends.signals import connection_created

from django.conf import settings
from django import VERSION as DjangoVersion
_DJANGO_VERSION = 30
'''
if DjangoVersion[:1] == (3):
    _DJANGO_VERSION = 30
else:
    if DjangoVersion[0] == 1:
        raise ImproperlyConfigured("Django %d.%d " % DjangoVersion[:2] + 
            "is not supported on 2.+ versions of django-pyodbc.  Please look " +
            "into the 1.x versions of django-pyodbc to see if your 1.x " +
            "version of Django is supported by django-pyodbc")
    else:
        raise ImproperlyConfigured("Django %d.%d is not supported." % DjangoVersion[:2])
'''

from django_dbmaker.operations import DatabaseOperations
from django_dbmaker.client import DatabaseClient
from django.utils import timezone
from django_dbmaker.creation import DatabaseCreation
from django_dbmaker.introspection import DatabaseIntrospection
from .schema import DatabaseSchemaEditor
from .features import DatabaseFeatures

DatabaseError = Database.Error
IntegrityError = Database.IntegrityError

class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'dbmaker'
    display_name = 'dbmaker'
    _DJANGO_VERSION = _DJANGO_VERSION
    drv_name = None
    MARS_Connection = False
    unicode_results = False
    datefirst = 7
    Database = Database
    limit_table_list = False
    is_dbmaker = True
    force_debug_cursor = True

    # Collations:       http://msdn2.microsoft.com/en-us/library/ms184391.aspx
    #                   http://msdn2.microsoft.com/en-us/library/ms179886.aspx
    # T-SQL LIKE:       http://msdn2.microsoft.com/en-us/library/ms179859.aspx
    # Full-Text search: http://msdn2.microsoft.com/en-us/library/ms142571.aspx
    #   CONTAINS:       http://msdn2.microsoft.com/en-us/library/ms187787.aspx
    #   FREETEXT:       http://msdn2.microsoft.com/en-us/library/ms176078.aspx
    data_types = {
        'AutoField':                    'serial',
        'BigAutoField':                 'bigserial',
        'BigIntegerField':              'bigint',
        'BinaryField':                  'blob',
        'BooleanField':                 'int',
        'CharField':                    'nvarchar(%(max_length)s)',
        'CommaSeparatedIntegerField':   'nvarchar(%(max_length)s)',
        'DateField':                    'date',
        'DateTimeField':                'timestamp',
        'DecimalField':                 'decimal(%(max_digits)s, %(decimal_places)s)',
        'DurationField':                'bigint',
        'FileField':                    'nvarchar(%(max_length)s)',
        'FilePathField':                'nvarchar(%(max_length)s)',
        'FloatField':                   'double',
        'GenericIPAddressField':        'nvarchar(39)',
        'IntegerField':                 'int',
        'IPAddressField':               'nvarchar(15)',
        'JSONField':                    'jsoncols',
        'LegacyDateField':              'timestamp',
        'LegacyDateTimeField':          'timestamp',
        'LegacyTimeField':              'time',
        'NewDateField':                 'date',
        'NewDateTimeField':             'timestamp',
        'NewTimeField':                 'time',
        'NullBooleanField':             'int',
        'OneToOneField':                'int',
        'PositiveIntegerField':         'int',
        'PositiveSmallIntegerField':    'smallint',
        'SlugField':                    'nvarchar(%(max_length)s)',
        'SmallAutoField':               'serial',
        'SmallIntegerField':            'smallint',
        'TextField':                    'nclob',
        'TimeField':                    'time',
        'UUIDField':                    'char(32)',       
    }

    data_type_check_constraints = {
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
        'iexact': '= %s',
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
                "PostgreSQL's limit of %d characters. Supply a shorter NAME "
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

    def get_new_connection(self, conn_params):
        connection = Database.connect(**conn_params)
        return connection

    def init_connection_state(self):
        cursor = self.create_cursor()
        cursor.execute("set string concat on")
        cursor.close()
        if not self.get_autocommit():
            self.commit()

    def _set_autocommit(self, autocommit):
        with self.wrap_database_errors:
            self.connection.autocommit = autocommit

    def _get_connection_string(self):
        settings_dict = self.settings_dict
        db_str, user_str, passwd_str, port_str = None, None, "", None
        options = settings_dict['OPTIONS']
        if settings_dict['NAME']:
            db_str = settings_dict['NAME']
        if settings_dict['HOST']:
            host_str = settings_dict['HOST']
        else:
            host_str = 'localhost'
        if settings_dict['USER']:
            user_str = settings_dict['USER']
        if settings_dict['PASSWORD']:
            passwd_str = settings_dict['PASSWORD']
        if settings_dict['PORT']:
            port_str = settings_dict['PORT']

        if not db_str:
            raise ImproperlyConfigured('You need to specify NAME in your Django settings file.')

        cstr_parts = []
        if 'driver' in options:
            driver = options['driver']
        else:
            driver = 'DBMaker 5.4 Driver'
   
        if 'dsn' in options:
            cstr_parts.append('DSN=%s' % options['dsn'])
        else:
            # Only append DRIVER if DATABASE_ODBC_DSN hasn't been set
            if os.path.isabs(driver):
                cstr_parts.append('DRIVER=%s' % driver)
            else:
                cstr_parts.append('DRIVER={%s}' % driver)

        if user_str:
            cstr_parts.append('UID=%s;PWD=%s' % (user_str, passwd_str))

        cstr_parts.append('DATABASE=%s' % db_str)
        connectionstring = ';'.join(cstr_parts)
        return connectionstring

    def create_cursor(self, name=None):
        return CursorWrapper(self.connection.cursor(), self)

    def _execute_foreach(self, sql, table_names=None):
        cursor = self.cursor()
        if not table_names:
            table_names = self.introspection.get_table_list(cursor)
        for table_name in table_names:
            cursor.execute(sql % self.ops.quote_name(table_name))

    def check_constraints(self, table_names=None):
        self.cursor().execute('CALL SETSYSTEMOPTION(\'FKCHK\', \'1\');')
         
    def disable_constraint_checking(self):
        # Windows Azure SQL Database doesn't support sp_msforeachtable
        #cursor.execute('EXEC sp_msforeachtable "ALTER TABLE ? NOCHECK CONSTRAINT ALL"')
        self.cursor().execute('CALL SETSYSTEMOPTION(\'FKCHK\', \'0\');')
        return True
               
    def enable_constraint_checking(self):
        # Windows Azure SQL Database doesn't support sp_msforeachtable
        #cursor.execute('EXEC sp_msforeachtable "ALTER TABLE ? WITH CHECK CHECK CONSTRAINT ALL"')
        self.check_constraints()
    
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
        self.active = True
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
            ( '(%s) AS' in sql) ) and params is not None:
            sql = sql % tuple(map(self.quote_value, params))
            return self.cursor.execute(sql)
        else:
            sql = self.format_sql(sql, len(params))
            params = self.format_params(params)
            self.last_params = params
            sql = sql.replace('%%', '%')
        try:
            return self.cursor.execute(sql, params)
        except IntegrityError:
            e = sys.exc_info()[1]
            raise utils.IntegrityError(*e.args)
        except DatabaseError:
            logger = logging.getLogger('django.db.backends')
            logger.setLevel(logging.ERROR)
            handler = logging.FileHandler('mylog.log')
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.error('DEBUG SQL')
            logger.error("----------------------------------------------------------------------------")
            logger.error(sql)
            logger.error(params)
            e = sys.exc_info()[1]
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
        needs_utc = _DJANGO_VERSION >= 14 and settings.USE_TZ
        if not (needs_utc):
            return tuple(rows)
        # FreeTDS (and other ODBC drivers?) don't support Unicode yet, so we
        # need to decode UTF-8 data coming from the DB
        fr = []
        for row in rows:
            if needs_utc and isinstance(row, datetime.datetime):
                row = row.replace(tzinfo=timezone.utc)
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


    # # MS SQL Server doesn't support explicit savepoint commits; savepoints are
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
    

# copied from Django 
# https://github.com/django/django/blob/0bf7b25f8f667d3710de91e91ae812efde05187c/django/db/backends/utils.py#L92
# Not optimized/refactored to maintain a semblance to the original code 
class CursorDebugWrapper(CursorWrapper):

    def execute(self, sql, params=()):
        start = time()
        try:
            return super().execute(sql, params)
        except Exception:
            stop = time()
            duration = stop - start
            logger.debug(
                'rc=%d: %s; args=%s', -1, sql, params,
            )

    def executemany(self, sql, param_list):
        start = time()
        return super().executemany(sql, param_list)
