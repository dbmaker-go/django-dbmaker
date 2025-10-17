import datetime
from django.db.backends.ddl_references import (
    Columns, ForeignKeyName, Statement, Table,
)
from django.db.backends.utils import split_identifier
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models import NOT_PROVIDED
from django.db.backends.base.schema import _related_non_m2m_objects



class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):
    
    sql_retablespace_table = "ALTER TABLE %(table)s MOVE TABLESPACE %(new_tablespace)s"
    sql_alter_column_type = "MODIFY COLUMN %(column)s TYPE TO %(type)s"
    sql_alter_column_null = "MODIFY COLUMN %(column)s NOT NULL TO NULL"
    sql_alter_column_not_null = "MODIFY COLUMN %(column)s NULL TO NOT NULL"
    sql_alter_column_default = "MODIFY COLUMN %(column)s SET DEFAULT %(default)s"
    sql_alter_column_no_default = "MODIFY COLUMN %(column)s DROP DEFAULT"
    sql_rename_column = "ALTER TABLE %(table)s MODIFY %(old_column)s NAME TO %(new_column)s"

    sql_create_check = "ALTER TABLE %(table)s MODIFY %(name)s CONSTRAINT to CHECK (%(check)s)"
    sql_delete_check = "ALTER TABLE %(table)s MODIFY %(name)s DROP CONSTRAINT"
    sql_delete_unique = "DROP INDEX %(name)s from %(table)s"
    sql_delete_fk = "ALTER TABLE %(table)s DROP FOREIGN KEY %(name)s"
    sql_delete_pk = "ALTER TABLE %(table)s DROP PRIMARY KEY"

    sql_delete_index = "DROP INDEX %(name)s FROM %(table)s"
    sql_create_fk = (
        "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s FOREIGN KEY (%(column)s) "
        "REFERENCES %(to_table)s (%(to_column)s) %(on_update)s %(deferrable)s"
    )
    sql_create_pk = "ALTER TABLE %(table)s ADD PRIMARY KEY (%(columns)s)"
    
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
       
        # Build the SQL and run it
        sql = self.sql_create_column % {
            "table": self.quote_name(model._meta.db_table),
            "column": self.quote_name(field.column),
            "definition": definition,
        }
        self.execute("set selinto commit 100;")
        self.execute(sql, params)
        # Drop the default if we need to
        # (Django usually does not use in-database defaults)
        if (
            not self.skip_default_on_alter(field)
            and self.effective_default(field) is not None
        ):
            changes_sql, params = self._alter_column_default_sql(
                model, None, field, drop=True
            )
            sql = self.sql_alter_column % {
                "table": self.quote_name(model._meta.db_table),
                "changes": changes_sql,
            }
            self.execute(sql, params)
        self.execute("set selinto commit 0;")
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
            return "'%s'" %  value.replace("\'", "\'\'")
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
                    #dbmaker nclob replace default_val to ''
                    if len(default_value)>31:
                        sql += " DEFAULT \'\'"
                    else:
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
        #dbmaker add give default_val if length of default_val >31
        if include_default:
            default_value = self.effective_default(field)
            if default_value is not None:
                if self.connection.features.requires_literal_defaults:
                    # Some databases can't take defaults as a parameter (oracle)
                    # If this is the case, the individual schema backend should
                    # implement prepare_default
                    #dbmaker nclob replace default_val to ''
                    if len(default_value)>31:
                        sql += " GIVE %s" % self.prepare_default(default_value)

        # Optionally add the tablespace if it's an implicitly indexed column
        tablespace = field.db_tablespace or model._meta.db_tablespace
        if tablespace and self.connection.features.supports_tablespaces and field.unique:
            sql += " %s" % self.connection.ops.tablespace_sql(tablespace, inline=True)
        # Return the sql
        return sql, params

    def _alter_field(self, model, old_field, new_field, old_type, new_type,
                     old_db_params, new_db_params, strict=False):
        """Perform a "physical" (non-ManyToMany) field update."""
        # Drop any FK constraints, we'll remake them later
        fks_dropped = set()
        if (
            self.connection.features.supports_foreign_keys and
            old_field.remote_field and
            old_field.db_constraint
        ):
            fk_names = self._constraint_names(model, [old_field.column], foreign_key=True)
            if strict and len(fk_names) != 1:
                raise ValueError("Found wrong number (%s) of foreign key constraints for %s.%s" % (
                    len(fk_names),
                    model._meta.db_table,
                    old_field.column,
                ))
            for fk_name in fk_names:
                fks_dropped.add((old_field.column,))
                self.execute(self._delete_fk_sql(model, fk_name))
        # Has unique been removed?
        if old_field.unique and (not new_field.unique or self._field_became_primary_key(old_field, new_field)):
            # Find the unique constraint for this field
            meta_constraint_names = {constraint.name for constraint in model._meta.constraints}
            constraint_names = self._constraint_names(
                model, [old_field.column], unique=True, primary_key=False,
                exclude=meta_constraint_names,
            )
            if strict and len(constraint_names) != 1:
                raise ValueError("Found wrong number (%s) of unique constraints for %s.%s" % (
                    len(constraint_names),
                    model._meta.db_table,
                    old_field.column,
                ))
            for constraint_name in constraint_names:
                self.execute(self._delete_unique_sql(model, constraint_name))
        # Drop incoming FK constraints if the field is a primary key or unique,
        # which might be a to_field target, and things are going to change.
        drop_foreign_keys = (
            self.connection.features.supports_foreign_keys and (
                (old_field.primary_key and new_field.primary_key) or
                (old_field.unique and new_field.unique)
            ) and old_type != new_type
        )
        if drop_foreign_keys:
            # '_meta.related_field' also contains M2M reverse fields, these
            # will be filtered out
            for _old_rel, new_rel in _related_non_m2m_objects(old_field, new_field):
                rel_fk_names = self._constraint_names(
                    new_rel.related_model, [new_rel.field.column], foreign_key=True
                )
                for fk_name in rel_fk_names:
                    self.execute(self._delete_fk_sql(new_rel.related_model, fk_name))
        # Removed an index? (no strict check, as multiple indexes are possible)
        # Remove indexes if db_index switched to False or a unique constraint
        # will now be used in lieu of an index. The following lines from the
        # truth table show all True cases; the rest are False:
        #
        # old_field.db_index | old_field.unique | new_field.db_index | new_field.unique
        # ------------------------------------------------------------------------------
        # True               | False            | False              | False
        # True               | False            | False              | True
        # True               | False            | True               | True
        if old_field.db_index and not old_field.unique and (not new_field.db_index or new_field.unique):
            # Find the index for this field
            meta_index_names = {index.name for index in model._meta.indexes}
            # Retrieve only BTREE indexes since this is what's created with
            # db_index=True.
            index_names = self._constraint_names(
                model, [old_field.column], index=True, type_=Index.suffix,
                exclude=meta_index_names,
            )
            for index_name in index_names:
                # The only way to check if an index was created with
                # db_index=True or with Index(['field'], name='foo')
                # is to look at its name (refs #28053).
                self.execute(self._delete_index_sql(model, index_name))
        #DBMaker only support alter column drop constraint
        if old_db_params['check'] != new_db_params['check'] and old_db_params['check']:       
            self.execute(self._delete_check_sql(model, old_field.column))
        # Have they renamed the column?
        if old_field.column != new_field.column:
            self.execute(self._rename_field_sql(model._meta.db_table, old_field, new_field, new_type))
            # Rename all references to the renamed column.
            for sql in self.deferred_sql:
                if isinstance(sql, Statement):
                    sql.rename_column_references(model._meta.db_table, old_field.column, new_field.column)
        # Next, start accumulating actions to do
        actions = []
        null_actions = []
        post_actions = []
        # Collation change?
        old_collation = getattr(old_field, 'db_collation', None)
        new_collation = getattr(new_field, 'db_collation', None)
        if old_collation != new_collation:
            # Collation change handles also a type change.
            fragment = self._alter_column_collation_sql(model, new_field, new_type, new_collation)
            actions.append(fragment)
        # Type change?
        elif old_type != new_type:
            fragment, other_actions = self._alter_column_type_sql(model, old_field, new_field, new_type, old_collation, new_collation)
            actions.append(fragment)
            post_actions.extend(other_actions)
        # When changing a column NULL constraint to NOT NULL with a given
        # default value, we need to perform 4 steps:
        #  1. Add a default for new incoming writes
        #  2. Update existing NULL rows with new default
        #  3. Replace NULL constraint with NOT NULL
        #  4. Drop the default again.
        # Default change?
        needs_database_default = False
        if old_field.null and not new_field.null:
            old_default = self.effective_default(old_field)
            new_default = self.effective_default(new_field)
            if (
                not self.skip_default_on_alter(new_field) and
                old_default != new_default and
                new_default is not None
            ):
                needs_database_default = True
                actions.append(self._alter_column_default_sql(model, old_field, new_field))
        # Nullability change?
        if old_field.null != new_field.null:
            fragment = self._alter_column_null_sql(model, old_field, new_field)
            if fragment:
                null_actions.append(fragment)
        # Only if we have a default and there is a change from NULL to NOT NULL
        four_way_default_alteration = (
            new_field.has_default() and
            (old_field.null and not new_field.null)
        )
        if actions or null_actions:
            if not four_way_default_alteration:
                # If we don't have to do a 4-way default alteration we can
                # directly run a (NOT) NULL alteration
                actions = actions + null_actions
            # Combine actions together if we can (e.g. postgres)
            if self.connection.features.supports_combined_alters and actions:
                sql, params = tuple(zip(*actions))
                actions = [(", ".join(sql), sum(params, []))]
            # Apply those actions
            for sql, params in actions:
                self.execute(
                    self.sql_alter_column % {
                        "table": self.quote_name(model._meta.db_table),
                        "changes": sql,
                    },
                    params,
                )
            if four_way_default_alteration:
                # Update existing rows with default value
                self.execute(
                    self.sql_update_with_default % {
                        "table": self.quote_name(model._meta.db_table),
                        "column": self.quote_name(new_field.column),
                        "default": "%s",
                    },
                    [new_default],
                )
                # Since we didn't run a NOT NULL change before we need to do it
                # now
                for sql, params in null_actions:
                    self.execute(
                        self.sql_alter_column % {
                            "table": self.quote_name(model._meta.db_table),
                            "changes": sql,
                        },
                        params,
                    )
        if post_actions:
            for sql, params in post_actions:
                self.execute(sql, params)
        # If primary_key changed to False, delete the primary key constraint.
        if old_field.primary_key and not new_field.primary_key:
            self._delete_primary_key(model, strict)
        # Added a unique?
        if self._unique_should_be_added(old_field, new_field):
            self.execute(self._create_unique_sql(model, [new_field]))
        # Added an index? Add an index if db_index switched to True or a unique
        # constraint will no longer be used in lieu of an index. The following
        # lines from the truth table show all True cases; the rest are False:
        #
        # old_field.db_index | old_field.unique | new_field.db_index | new_field.unique
        # ------------------------------------------------------------------------------
        # False              | False            | True               | False
        # False              | True             | True               | False
        # True               | True             | True               | False
        if (not old_field.db_index or old_field.unique) and new_field.db_index and not new_field.unique:
            self.execute(self._create_index_sql(model, fields=[new_field]))
        # Type alteration on primary key? Then we need to alter the column
        # referring to us.
        rels_to_update = []
        if drop_foreign_keys:
            rels_to_update.extend(_related_non_m2m_objects(old_field, new_field))
        # Changed to become primary key?
        if self._field_became_primary_key(old_field, new_field):
            # Make the new one
            self.execute(self._create_primary_key_sql(model, new_field))
            # Update all referencing columns
            rels_to_update.extend(_related_non_m2m_objects(old_field, new_field))
        # Handle our type alters on the other end of rels from the PK stuff above
        for old_rel, new_rel in rels_to_update:
            rel_db_params = new_rel.field.db_parameters(connection=self.connection)
            rel_type = rel_db_params['type']
            fragment, other_actions = self._alter_column_type_sql(
                new_rel.related_model, old_rel.field, new_rel.field, rel_type, old_collation, new_collation
            )
            self.execute(
                self.sql_alter_column % {
                    "table": self.quote_name(new_rel.related_model._meta.db_table),
                    "changes": fragment[0],
                },
                fragment[1],
            )
            for sql, params in other_actions:
                self.execute(sql, params)
        # Does it have a foreign key?
        if (self.connection.features.supports_foreign_keys and new_field.remote_field and
                (fks_dropped or not old_field.remote_field or not old_field.db_constraint) and
                new_field.db_constraint):
            self.execute(self._create_fk_sql(model, new_field, "_fk_%(to_table)s_%(to_column)s"))
        # Rebuild FKs that pointed to us if we previously had to drop them
        if drop_foreign_keys:
            for _, rel in rels_to_update:
                if rel.field.db_constraint:
                    self.execute(self._create_fk_sql(rel.related_model, rel.field, "_fk"))
        #DBMaker only support alter column constraint to 
        if old_db_params['check'] != new_db_params['check'] and new_db_params['check']:
            self.execute(self._create_check_sql(model, new_field.column, new_db_params['check']))
        # Drop the default if we need to
        # (Django usually does not use in-database defaults)
        if needs_database_default:
            changes_sql, params = self._alter_column_default_sql(model, old_field, new_field, drop=True)
            sql = self.sql_alter_column % {
                "table": self.quote_name(model._meta.db_table),
                "changes": changes_sql,
            }
            self.execute(sql, params)
        # Reset connection if required
        if self.connection.features.connection_persists_old_columns:
            self.connection.close()
        
    def prepare_default(self, value):
        return self.quote_value(value)
    
    def _collate_sql(self, collation, old_collation=None, table_name=None):
        if collation is None and old_collation is not None:
            collation = self._get_default_collation(table_name)
        return super()._collate_sql(collation, old_collation, table_name)