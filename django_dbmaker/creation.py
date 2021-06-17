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
import subprocess
import os
from django.db.backends.base.creation import BaseDatabaseCreation

class DatabaseCreation(BaseDatabaseCreation):
    # This dictionary maps Field objects to their associated MS SQL column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    #
    # Any format strings starting with "qn_" are quoted before being used in the
    # output (the "qn_" prefix is stripped before the lookup is performed.

    
    # For these columns, DBMaker doesn't:
    # - accept default values and implicitly treats these columns as nullable
    
    def _create_test_db(self, verbosity=1, autoclobber=False, keepdb=False):
        settings_dict = self.connection.settings_dict

        if self.connection._DJANGO_VERSION >= 13:
            test_name = self._get_test_db_name()
        else:
            if settings_dict['TEST_NAME']:
                test_name = settings_dict['TEST_NAME']
            else:
                try:
                    from django.db.backends.base.creation import TEST_DATABASE_PREFIX
                except ImportError:
                    # import location prior to Django 1.8
                    from django.db.backends.creation import TEST_DATABASE_PREFIX
                test_name = TEST_DATABASE_PREFIX + settings_dict['NAME']
        if self.connection._DJANGO_VERSION >= 17:
            settings_dict['TEST']['NAME'] = test_name
        else:
            if not settings_dict['TEST_NAME']:
                settings_dict['TEST_NAME'] = test_name

        if not self.connection.test_create:
            '''
            # use the existing database instead of creating a new one
            if verbosity >= 1:
                print("Dropping tables ... ")

            self.connection.close()
            settings_dict["NAME"] = test_name
            cursor = self.connection.cursor()
            qn = self.connection.ops.quote_name
            sql = "SELECT distinct trim(FK_TBL_NAME), trim(PK_TBL_NAME) FROM SYSFOREIGNKEY" 
            cursor.execute("CALL SETSYSTEMOPTION(\'FKCHK\', \'0\')")
            
            for row in cursor.execute(sql).fetchall():
                cursor.execute("DROP TABLE %s" % row[0])
                cursor.execute("DROP TABLE %s" % row[1])
           
            cursor.execute('CALL SETSYSTEMOPTION(\'FKCHK\', \'1\')')
            self.connection.connection.commit()
            '''
            
            return test_name

        return super(DatabaseCreation, self)._create_test_db(verbosity, autoclobber)
    """
    def _execute_create_test_db(self, cursor, parameters, keepdb=False):
        creatdb = ['C:\\DBMaker\\5.4\\bin\\dmsql32' , 'C:\\DBMaker\\5.4\\bin\\createdb.sql', '/b']
        startdb = ['C:\\DBMaker\\5.4\\bin\\dmserver', 'test_utf8db', '/b']
        try:
            with subprocess.Popen(createdb, stdout=subprocess.DEVNULL) as dump_proc:
                with subprocess.Popen(startdb, stdout=subprocess.DEVNULL):
                    dump_proc.stdout.close()
        except Exception as e:
            self.log('create database: %s' % e)
            sys.exit(2)    
        
    """
    def _destroy_test_db(self, test_database_name, verbosity):
        "Internal implementation - remove the test db tables."
        if test_database_name:
            # Remove the SQLite database file
            os.remove(test_database_name)

    def _clone_test_db(self, suffix, verbosity, keepdb=False):
        source_database_name = self.connection.settings_dict['NAME']
        target_database_name = self.get_test_db_clone_settings(suffix)['NAME']
        test_db_params = {
            'dbname': self.connection.ops.quote_name(target_database_name),
            'suffix': self.sql_table_creation_suffix(),
        }
        with self._nodb_connection.cursor() as cursor:
            try:
                self._execute_create_test_db(cursor, test_db_params, keepdb)
            except Exception:
                if keepdb:
                    # If the database should be kept, skip everything else.
                    return
                try:
                    if verbosity >= 1:
                        self.log('Destroying old test database for alias %s...' % (
                            self._get_database_display_str(verbosity, target_database_name),
                        ))
                    self._destroy_test_db(test_db_params)
                    self._execute_create_test_db(cursor, test_db_params, keepdb)
                except Exception as e:
                    self.log('Got an error recreating the test database: %s' % e)
                    sys.exit(2)
        self._clone_db(source_database_name, target_database_name)

    def _clone_db(self, source_database_name, target_database_name):
        dump_args = DatabaseClient.settings_to_cmd_args(self.connection.settings_dict)[1:]
        dump_args[-1] = source_database_name
        dump_cmd = ['mysqldump', '--routines', '--events'] + dump_args
        load_cmd = DatabaseClient.settings_to_cmd_args(self.connection.settings_dict)
        load_cmd[-1] = target_database_name

        with subprocess.Popen(dump_cmd, stdout=subprocess.PIPE) as dump_proc:
            with subprocess.Popen(load_cmd, stdin=dump_proc.stdout, stdout=subprocess.DEVNULL):
                # Allow dump_proc to receive a SIGPIPE if the load process exits.
                dump_proc.stdout.close()
            