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

import pyodbc as Database
from django.db.backends.base.introspection import (
    BaseDatabaseIntrospection, FieldInfo, TableInfo,
)
import sqlparse
from django.utils.datastructures import OrderedSet
SQL_AUTOFIELD = -777555
SQL_BIGAUTOFIELD = -777444

class DatabaseIntrospection(BaseDatabaseIntrospection):
    # Map type codes to Django Field types.
    data_types_reverse = {
        SQL_AUTOFIELD:                  'AutoField',
        SQL_BIGAUTOFIELD:               'BigAutoField',
        Database.SQL_BIGINT:            'BigIntegerField',
        Database.SQL_BINARY:            'BinaryField',
        Database.SQL_BIT:               'NullBooleanField',
        Database.SQL_CHAR:              'CharField',
        Database.SQL_DECIMAL:           'DecimalField',
        Database.SQL_DOUBLE:            'FloatField',
        Database.SQL_FLOAT:             'FloatField',
#        Database.SQL_GUID:              'TextField',
        Database.SQL_INTEGER:           'IntegerField',
        Database.SQL_LONGVARBINARY:     'BinaryField',
        #Database.SQL_LONGVARCHAR:       ,
        Database.SQL_NUMERIC:           'DecimalField',
        Database.SQL_REAL:              'FloatField',
        Database.SQL_SMALLINT:          'SmallIntegerField',
        Database.SQL_TINYINT:           'SmallIntegerField',
        Database.SQL_TYPE_DATE:         'DateField',
        Database.SQL_TYPE_TIME:         'TimeField',
        Database.SQL_TYPE_TIMESTAMP:    'DateTimeField',
        Database.SQL_VARBINARY:         'BinaryField',
        Database.SQL_VARCHAR:           'TextField',
        Database.SQL_WCHAR:             'CharField',
        Database.SQL_WLONGVARCHAR:      'TextField',
        Database.SQL_WVARCHAR:          'CharField',
    }

    def get_table_list(self, cursor):
        """
        Returns a list of table names in the current database.
        """
        cursor.execute("SELECT trim(TABLE_NAME), trim(TABLE_TYPE) FROM INFORMATION_SCHEMA.TABLES")
        types = {'TABLE': 't', 'VIEW': 'v'}
        return [TableInfo(self.identifier_converter(row[0]), types.get(row[1])) for row in cursor.fetchall()]

    def _is_auto_field(self, cursor, table_name, column_name):
        """
        Checks whether column is Identity
        """
        # COLUMNPROPERTY: http://msdn2.microsoft.com/en-us/library/ms174968.aspx

        #from django.db import connection
        #cursor.execute("SELECT COLUMNPROPERTY(OBJECT_ID(%s), %s, 'IsIdentity')",
        #                 (connection.ops.quote_name(table_name), column_name))
        cursor.execute("SELECT COUNT(*) FROM SYSCOLUMN WHERE TABLE_NAME = UPPER(%s) AND COLUMN_NAME=UPPER(%s) AND (TYPE_NAME='SERIAL' OR TYPE_NAME='BIGSERAL')",
                         (self.connection.ops.quote_name(table_name), column_name))
        return cursor.fetchall()[0][0]

    def get_table_description(self, cursor, table_name, identity_check=True):
        """Returns a description of the table, with DB-API cursor.description interface.
        """

        # map pyodbc's cursor.columns to db-api cursor description
        columns = [[c[3], c[4], None, c[6], c[6], c[8], c[10], c[12]] for c in cursor.columns(table=table_name)]
        items = []
        for column in columns:
            column[0] = self.identifier_converter(column[0])
            if identity_check and self._is_auto_field(cursor, table_name, column[0]):
                column[1] = SQL_AUTOFIELD
            items.append(FieldInfo(*column))
            
        return items  
    
    def identifier_converter(self, name):
        """Identifier comparison is case insensitive under Oracle."""
        return name.lower()
    
    def colname(self, cursor, table_name): 
        colnames = [self.identifier_converter(c[3]) for c in cursor.columns(table=table_name)]
        return colnames
                
    def _bytes_to_list(self, bytes):
        
        #based 0
        item = []  
        i = 0
        columnid = int.from_bytes(bytes[i*2:(i+1)*2], byteorder='little', signed=False)-1;
        while (columnid >= 0):
            i += 1
            item.append(columnid)
            #base 0, so actual column_order-1 will be the index of column_name
            columnid= int.from_bytes(bytes[i*2:(i+1)*2], byteorder='little', signed=False)-1
        return item
          
    def get_relations(self, cursor, table_name):
        """
        Return a dictionary of {field_name: (field_name_other_table, other_table)}
        representing all relationships to the given table.
        """
        constraints = self.get_key_columns(cursor, table_name)
        relations = {}
        for my_fieldname, other_table, other_field in constraints:
            relations[my_fieldname] = (other_field, other_table)
        return relations

    #def get_collations_list(self, cursor):
    #    """
    #    Returns list of available collations and theirs descriptions.
    #    """
    #    # http://msdn2.microsoft.com/en-us/library/ms184391.aspx
    #    # http://msdn2.microsoft.com/en-us/library/ms179886.aspx
    #
    #    cursor.execute("SELECT name, description FROM ::fn_helpcollations()")
    #    return [tuple(row) for row in cursor.fetchall()]

    def get_key_columns(self, cursor, table_name):
        """
        Backends can override this to return a list of (column_name, referenced_table_name,
        referenced_column_name) for all key columns in given table.
        """
        sql = """
SELECT 
  PK_COL_ORDER,
  TRIM(PK_TBL_NAME) AS referenced_table_name,
  FK_COL_ORDER
FROM SYSTEM.SYSFOREIGNKEY 
WHERE FK_TBL_NAME = Upper(%s) """
        cursor.execute(sql, (table_name,))
        foreignKeyInfo = cursor.fetchall()
        foreignKeys = []

        for pk_col_order, referenced_table_name, fk_col_order in foreignKeyInfo:
            pkcolIndex = self._bytes_to_list(pk_col_order)
            fkcolIndex = self._bytes_to_list(fk_col_order)
            i = 0
            while (i<len(pkcolIndex)):
                foreignKeys.append((self.colname(cursor, table_name)[fkcolIndex[i]], self.identifier_converter(referenced_table_name), self.colname(cursor, referenced_table_name)[pkcolIndex[i]]))
                i += 1
            
        return foreignKeys;

    def get_sequences(self, cursor, table_name, table_fields=()):
        for f in table_fields:
            if isinstance(f, models.AutoField):
                return [{'table': table_name, 'column': f.column}]
        return []
    
    def _parse_column_constraint(self, sql, columns):
        statement = sqlparse.parse(sql)[0]
        tokens = (token for token in statement.flatten() if not token.is_whitespace)
        braces_deep = 0
        check_columns=[]
        for token in tokens:
            if token.match(sqlparse.tokens.Punctuation, '('):
                braces_deep += 1
            elif token.match(sqlparse.tokens.Punctuation, ')'):
                braces_deep -= 1
                if braces_deep < 0:
                    # End of columns and constraints for table definition.
                    break
            elif braces_deep == 0 and token.match(sqlparse.tokens.Punctuation, ','):
                # End of current column or constraint definition.
                break
            
            if token.ttype in (sqlparse.tokens.Name, sqlparse.tokens.Keyword):
                if token.value in columns:
                    check_columns.append(token.value)
            elif token.ttype == sqlparse.tokens.Literal.String.Symbol:
                if token.value[1:-1] in columns:
                    check_columns.append(token.value[1:-1])
        
        return check_columns
            
    def get_constraints(self, cursor, table_name):
        """
        Retrieve any constraints or keys (unique, pk, fk, check, index)
        across one or more columns.

        Return a dict mapping constraint names to their attributes,
        where attributes is a dict with keys:
         * columns: List of columns this covers
         * primary_key: True if primary key, False otherwise
         * unique: True if this is a unique constraint, False otherwise
         * foreign_key: (table, column) of target, or None
         * check: True if check constraint, False otherwise
         * index: True if index, False otherwise.
         * orders: The order (ASC/DESC) defined for the columns of indexes
         * type: The type of the index (btree, hash, etc.)

        Some backends may return special constraint names that don't exist
        if they don't name constraints of a certain type (e.g. SQLite)
        """
        """
        Retrieve any constraints or keys (unique, pk, fk, check, index) across
        one or more columns.
        """
        constraints = {}
        # Get the foreign keys
        query = """
            SELECT fk_name, fk_col_order, pk_tbl_name, pk_col_order
            FROM system.sysforeignkey
            WHERE fk_tbl_name = upper(%s)
        """
        cursor.execute(query, [table_name])
        for constraint, fk_col_order, pk_tbl_name, pk_col_order in cursor.fetchall():
            constraint = self.identifier_converter(constraint)
            pkcolIndex = self._bytes_to_list(pk_col_order)
            fkcolIndex = self._bytes_to_list(fk_col_order)
            fkcollist = []
            pkcollist = []
            i = 0
            while (i<len(fkcolIndex)):
                fkcollist.append(self.colname(cursor, table_name)[fkcolIndex[i]])
                pkcollist.append(self.colname(cursor, table_name)[pkcolIndex[i]])
                i += 1
            constraints[constraint] = {
                'columns': fkcollist,
                'primary_key': False,
                'unique': False,
                'index': False,
                'check': False,
                'foreign_key': (self.identifier_converter(pk_tbl_name), pkcollist),
                }
    
        #indexes (primary, unique, index)
        cursor.execute("call SHOWINDEX('sysadm', '%s')" % table_name)
        for table, non_unique, index, type_, colseq, column, asc_or_desc in [x[1:8] for x in cursor.fetchall()]:
            index = self.identifier_converter(index)
            if index not in constraints:
                constraints[index] = {
                    'columns': OrderedSet(),
                    'primary_key': True if index=='primarykey' else False,
                    'unique': True if non_unique==0 else False,
                    'order': 'ASC' if asc_or_desc == 'A' else 'DESC',
                    'index': True if index != 'primarykey' else False, 
                }
            constraints[index]['columns'].add(self.identifier_converter(column))    
            constraints[index]['type'] = 'idx' if type_ == 3 else type_
            constraints[index]['check'] = False
            constraints[index]['foreign_key'] = None
        
        #column constraint
        query = """
            SELECT constr, column_name
            FROM system.syscolumn
            WHERE table_name = upper(%s) AND BLOBLEN(CONSTR)>0
        """
        cursor.execute(query, [table_name])
        
        unnamed_constrains_index = 0
        for sql, column in cursor.fetchall():
            sql = sql.replace('value', self.identifier_converter(column)) 
            check_columns = self._parse_column_constraint(sql, self.colname(cursor, table_name));
            unnamed_constrains_index += 1
            constraints['__unnamed_constraint_%s__' % unnamed_constrains_index] = {
                'check': True,
                'columns': check_columns,
                'primary_key': False,
                'unique': False,
                'foreign_key': None,
                'index': False,
            } if check_columns else None
            
        #table constraint
        query = """
            SELECT constr
            FROM system.systable
            WHERE table_name = upper(%s) AND BLOBLEN(CONSTR)>0
        """
        cursor.execute(query, [table_name])
        
        #table constraint
        for sql in cursor.fetchall():
            check_columns = self._parse_column_constraint(sql[0], self.colname(cursor, table_name));
            unnamed_constrains_index += 1
            constraints['__unnamed_constraint_%s__' % unnamed_constrains_index] = {
                'check': True,
                'columns': check_columns,
                'primary_key': False,
                'unique': False,
                'foreign_key': None,
                'index': False,
            } if check_columns else None   
        
        for constraint in constraints.values():
            constraint['columns'] = list(constraint['columns'])
        return constraints