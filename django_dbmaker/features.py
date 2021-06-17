from django.db.backends.base.features import BaseDatabaseFeatures
from django.utils.functional import cached_property

class DatabaseFeatures(BaseDatabaseFeatures):
    can_use_chunked_reads = False
    supports_microsecond_precision = False
    supports_regex_backreferencing = False
    supports_subqueries_in_group_by = False
    supports_transactions = True
    allow_sliced_subqueries = False
    supports_paramstyle_pyformat = False

    has_bulk_insert = False
    # DateTimeField doesn't support timezones, only DateTimeOffsetField
    has_zoneinfo_database = False
    supports_timezones = False
    supports_sequence_reset = False
    supports_tablespaces = True
    ignores_nulls_in_unique_constraints = False
    can_introspect_autofield = True
    has_case_insensitive_like = False
    requires_literal_defaults = True
    introspected_boolean_field_type = 'IntegerField'
    can_introspect_small_integer_field = True
    supports_index_on_text_field = False
    implied_column_null = True
    supports_select_intersection = False
    supports_select_difference = False
    update_can_self_select = False
    has_zoneinfo_database = False
    supports_ignore_conflicts = False
    allow_sliced_subqueries_with_in = False
    order_by_nulls_first = True
    supports_json_field_contains = False
    supports_collation_on_textfield = False
    has_native_json_field = True
    has_json_operators = True
    json_key_contains_list_matching_requires_list = True

    # Does the backend support NULLS FIRST and NULLS LAST in ORDER BY?
    supports_order_by_nulls_modifier = False
    supports_json_field = False
#    case_whennot_not_supported = True

    @cached_property
    def introspected_field_types(self):
        return {
            **super().introspected_field_types,
            'PositiveBigIntegerField': 'BigIntegerField',
            'PositiveIntegerField': 'IntegerField',
            'PositiveSmallIntegerField': 'SmallIntegerField',
            'SmallAutoField': 'AutoField',
            'DurationField': 'BigIntegerField',
        }
