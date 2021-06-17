import datetime
from django.db.backends.ddl_references import (
    Columns, ForeignKeyName, Statement, Table,
)
from django.db.backends.utils import split_identifier
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models import NOT_PROVIDED


class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):
    
    sql_retablespace_table = "ALTER TABLE %(table)s MOVE TABLESPACE %(new_tablespace)s"
    sql_alter_column_type = "MODIFY COLUMN %(column)s TYPE TO %(type)s"
    sql_alter_column_null = "MODIFY COLUMN %(column)s NOT NULL TO NULL"
    sql_alter_column_not_null = "MODIFY COLUMN %(column)s NULL TO NOT NULL"
    sql_alter_column_default = "MODIFY COLUMN %(column)s SET DEFAULT %(default)s"
    sql_alter_column_no_default = "MODIFY COLUMN %(column)s DROP DEFAULT"
    sql_rename_column = "ALTER TABLE %(table)s MODIFY %(old_column)s NAME TO %(new_column)s"

    sql_create_check = "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s CHECK (%(check)s)"
    sql_delete_check = "ALTER TABLE %(table)s MODIFY %(column)s DROP CONSTRAINT"

    sql_delete_unique = "ALTER TABLE %(table)s MODIFY %(column)s DROP CONSTRAINT"

   
    sql_create_inline_fk = None
    sql_delete_fk = "ALTER TABLE %(table)s DROP FOREIGN KEY %(name)s"
    sql_delete_pk = "ALTER TABLE %(table)s DROP PRIMARY KEY %(name)s"

    sql_delete_index = "DROP INDEX %(name)s FROM %(table)s"
    sql_create_fk = (
        "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s FOREIGN KEY (%(column)s) "
        "REFERENCES %(to_table)s (%(to_column)s) %(on_update)s %(deferrable)s"
    )
   
    def _is_limited_data_type(self, field):
        db_type = field.db_type(self.connection)
        return db_type is not None and db_type.lower() in self.connection._limited_data_types

    def skip_default(self, field):
        return self._is_limited_data_type(field)
    
    def add_field(self, model, field):
        """
        Create a field on a model. Usually involves adding a column, but may
        involve adding a table instead (for M2M fields).
        """
        # Special-case implicit M2M tables
        if field.many_to_many and field.remote_field.through._meta.auto_created:
            return self.create_model(field.remote_field.through)
        # Get the column's definition
                    
        definition, params = self.column_sql(model, field, include_default=True)
        # It might not actually have a column behind it
        if definition is None:
            return
        #dbmaker don't support unique in add column
        if 'UNIQUE' in definition:
            definition = definition.replace('UNIQUE', '')
            self.deferred_sql.append(self._create_unique_sql(model, [field.column]))
             
        # Check constraints can go on the column SQL here
        db_params = field.db_parameters(connection=self.connection)
        if db_params['check']:
            definition += " " + self.sql_check_constraint % db_params
        
        #dbmaker need add give val in default val not null       
        default_val = self.effective_default(field)
        needs_give = (
            not field.null and
            default_val is not None and
            not self.skip_default(field) and
            self.connection.features.requires_literal_defaults
        )
        if needs_give:
            default = self.prepare_default(default_val)
            definition += " give " + default
            
        # Build the SQL and run it
        sql = self.sql_create_column % {
            "table": self.quote_name(model._meta.db_table),
            "column": self.quote_name(field.column),
            "definition": definition,
        }
        self.execute(sql, params)
        # Drop the default if we need to
        # (Django usually does not use in-database defaults)
        if not self.skip_default(field) and self.effective_default(field) is not None:
            changes_sql, params = self._alter_column_default_sql(model, None, field, drop=True)
            sql = self.sql_alter_column % {
                "table": self.quote_name(model._meta.db_table),
                "changes": changes_sql,
            }
            self.execute(sql, params)
        # Add an index, if required
        self.deferred_sql.extend(self._field_indexes_sql(model, field))
        # Add any FK constraints later
        if field.remote_field and self.connection.features.supports_foreign_keys and field.db_constraint:
            self.deferred_sql.append(self._create_fk_sql(model, field, "_fk_%(to_table)s_%(to_column)s"))
        # Reset connection if required
        if self.connection.features.connection_persists_old_columns:
            self.connection.close()

    def _create_fk_sql(self, model, field, suffix):
        def create_fk_name(*args, **kwargs):
            return self.quote_name(self._create_index_name(*args, **kwargs))

        table = Table(model._meta.db_table, self.quote_name)
        name = ForeignKeyName(
            model._meta.db_table,
            [field.column],
            split_identifier(field.target_field.model._meta.db_table)[1],
            [field.target_field.column],
            suffix,
            create_fk_name,
        )
        column = Columns(model._meta.db_table, [field.column], self.quote_name)
        to_table = Table(field.target_field.model._meta.db_table, self.quote_name)
        to_column = Columns(field.target_field.model._meta.db_table, [field.target_field.column], self.quote_name)
        deferrable = self.connection.ops.deferrable_sql()
        table_name = model._meta.db_table
        to_table_name = field.target_field.model._meta.db_table
        if(table_name == to_table_name):
            return Statement(
                self.sql_create_fk,
                table=table,
                name=name,
                column=column,
                to_table=to_table,
                to_column=to_column,
                on_update="",
                deferrable=deferrable,
            )    
        else:
            return Statement(
                self.sql_create_fk,
                table=table,
                name=name,
                column=column,
                to_table=to_table,
                to_column=to_column,
                on_update="ON UPDATE CASCADE",
                deferrable=deferrable,
            
            )
        
    def quote_value(self, value):
        if isinstance(value, (datetime.date, datetime.time, datetime.datetime)):
            return "'%s'" % value
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

    def column_sql(self, model, field, include_default=False):
        """
        Takes a field and returns its column definition.
        The field must already have had set_attributes_from_name called.
        """
        # Get the column's type and use that as the basis of the SQL
        db_params = field.db_parameters(connection=self.connection)
        sql = db_params['type']
        params = []
        # Check for fields that aren't actually columns (e.g. M2M)
        if sql is None:
            return None, None
        # Work out nullability
        null = field.null
        # If we were told to include a default value, do so
        include_default = include_default and not self.skip_default(field)
        if include_default:
            default_value = self.effective_default(field)
            if default_value is not None:
                if self.connection.features.requires_literal_defaults:
                    # Some databases can't take defaults as a parameter (oracle)
                    # If this is the case, the individual schema backend should
                    # implement prepare_default
                    sql += " DEFAULT %s" % self.prepare_default(default_value)
                else:
                    sql += " DEFAULT %s"
                    params += [default_value]
        
        if (field.empty_strings_allowed and not field.primary_key and
                self.connection.features.interprets_empty_strings_as_nulls):
            null = True
        if null and not self.connection.features.implied_column_null:
            sql += " NULL"
        elif not null and field.get_internal_type() not in ('SmallAutoField', 'AutoField', 'BigAutoField', 'JSONField'):
            sql += " NOT NULL"
        # Primary key/unique outputs
        if field.primary_key:
            sql += " PRIMARY KEY"
        elif field.unique:
            sql += " UNIQUE"
        # Optionally add the tablespace if it's an implicitly indexed column
        tablespace = field.db_tablespace or model._meta.db_tablespace
        if tablespace and self.connection.features.supports_tablespaces and field.unique:
            sql += " %s" % self.connection.ops.tablespace_sql(tablespace, inline=True)
        # Return the sql
        return sql, params   
   
    def _alter_column_type_sql(self, table, old_field, new_field, new_type):
        return super(DatabaseSchemaEditor, self)._alter_column_type_sql(table, old_field, new_field, new_type)
    
    def prepare_default(self, value):
        return self.quote_value(value)
    
    def _rename_field_sql(self, table, old_field, new_field, new_type):
#        new_type = self._set_field_new_type_null_status(old_field, new_type)
        return super(DatabaseSchemaEditor, self)._rename_field_sql(table, old_field, new_field, new_type)
