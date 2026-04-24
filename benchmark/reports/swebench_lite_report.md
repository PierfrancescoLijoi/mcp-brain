# mcp-brain SWE-bench Lite benchmark report

## Summary

- Instances evaluated: **300**
- Errors: **0**
- Avg gold files: **1.00**
- Avg predicted files: **10.00**

| Metric | @1 | @3 | @5 | @10 |
|---|---:|---:|---:|---:|
| Hit | 0.187 | 0.370 | 0.463 | 0.600 |
| Recall | 0.187 | 0.370 | 0.463 | 0.600 |
| MAP | 0.187 | 0.266 | 0.287 | 0.306 |

## Worst misses / examples

### django__django-10914 — django/django
- Gold: `django/conf/global_settings.py`
- Predicted: `django/contrib/sessions/backends/file.py, django/core/files/storage.py, django/contrib/staticfiles/storage.py, django/core/files/uploadhandler.py, tests/file_uploads/tests.py, django/contrib/staticfiles/management/commands/collectstatic.py, django/core/files/uploadedfile.py, django/contrib/staticfiles/handlers.py, django/contrib/staticfiles/finders.py, django/contrib/auth/migrations/0011_update_proxy_permissions.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11001 — django/django
- Gold: `django/db/models/sql/compiler.py`
- Predicted: `django/db/backends/mysql/compiler.py, django/contrib/postgres/search.py, django/core/management/sql.py, django/db/models/functions/datetime.py, tests/forms_tests/widget_tests/test_splithiddendatetimewidget.py, django/db/backends/postgresql/introspection.py, django/db/backends/sqlite3/operations.py, django/db/backends/mysql/introspection.py, django/contrib/gis/db/backends/mysql/introspection.py, django/db/backends/postgresql/operations.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11564 — django/django
- Gold: `django/conf/__init__.py`
- Predicted: `django/contrib/staticfiles/management/commands/collectstatic.py, django/contrib/staticfiles/urls.py, django/contrib/staticfiles/management/commands/findstatic.py, django/contrib/staticfiles/checks.py, django/contrib/staticfiles/finders.py, django/contrib/staticfiles/management/commands/runserver.py, django/contrib/staticfiles/views.py, django/contrib/staticfiles/apps.py, django/contrib/staticfiles/utils.py, django/contrib/staticfiles/storage.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11583 — django/django
- Gold: `django/utils/autoreload.py`
- Predicted: `django/core/management/__init__.py, django/core/management/commands/runserver.py, django/contrib/staticfiles/management/commands/findstatic.py, django/contrib/staticfiles/management/commands/runserver.py, django/core/management/commands/startproject.py, django/core/management/commands/startapp.py, django/contrib/staticfiles/management/commands/collectstatic.py, django/core/management/commands/check.py, django/db/models/fields/files.py, django/core/management/commands/showmigrations.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11630 — django/django
- Gold: `django/core/checks/model_checks.py`
- Predicted: `django/contrib/gis/db/backends/postgis/base.py, django/db/models/base.py, django/db/backends/dummy/base.py, django/contrib/gis/db/backends/spatialite/base.py, django/db/backends/oracle/base.py, django/template/backends/base.py, django/core/cache/backends/base.py, django/db/backends/sqlite3/base.py, django/db/backends/mysql/base.py, django/contrib/sessions/backends/base.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11742 — django/django
- Gold: `django/db/models/fields/__init__.py`
- Predicted: `tests/migrations/test_writer.py, tests/migrations/test_operations.py, tests/gis_tests/gis_migrations/test_operations.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, tests/migrations/test_base.py, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py, django/contrib/auth/migrations/0008_alter_user_username_max_length.py, django/contrib/auth/migrations/0003_alter_user_email_max_length.py, django/contrib/auth/migrations/0002_alter_permission_name_max_length.py, django/db/migrations/loader.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11797 — django/django
- Gold: `django/db/models/lookups.py`
- Predicted: `django/contrib/auth/migrations/0003_alter_user_email_max_length.py, tests/migrations/test_writer.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/contrib/auth/migrations/0005_alter_user_last_login_null.py, tests/migrations/test_operations.py, django/core/management/commands/makemigrations.py, tests/gis_tests/gis_migrations/test_operations.py, django/contrib/auth/migrations/0008_alter_user_username_max_length.py, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py, tests/migrations/test_base.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11815 — django/django
- Gold: `django/db/migrations/serializer.py`
- Predicted: `django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py, django/contrib/auth/migrations/0002_alter_permission_name_max_length.py, django/contrib/auth/migrations/0008_alter_user_username_max_length.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/db/migrations/operations/models.py, django/core/management/commands/makemigrations.py, tests/migrations/test_base.py, tests/migrations/test_writer.py, tests/gis_tests/gis_migrations/test_operations.py, django/contrib/auth/migrations/0003_alter_user_email_max_length.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11910 — django/django
- Gold: `django/db/migrations/autodetector.py`
- Predicted: `django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/contrib/auth/migrations/0002_alter_permission_name_max_length.py, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py, tests/migrations/test_operations.py, django/db/migrations/loader.py, django/core/management/commands/makemigrations.py, django/contrib/auth/migrations/0008_alter_user_username_max_length.py, tests/gis_tests/gis_migrations/test_operations.py, tests/migrations/test_base.py, tests/migrations/test_writer.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12113 — django/django
- Gold: `django/db/backends/sqlite3/creation.py`
- Predicted: `django/contrib/gis/db/backends/spatialite/base.py, django/db/backends/sqlite3/base.py, django/db/backends/postgresql/base.py, django/contrib/gis/db/backends/postgis/base.py, django/db/models/sql/compiler.py, django/db/backends/mysql/base.py, django/db/backends/sqlite3/operations.py, tests/admin_views/test_multidb.py, tests/backends/sqlite/tests.py, django/contrib/gis/db/backends/mysql/base.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12125 — django/django
- Gold: `django/db/migrations/serializer.py`
- Predicted: `django/db/migrations/state.py, django/db/models/fields/related.py, django/db/models/fields/__init__.py, django/db/models/fields/reverse_related.py, django/db/models/fields/related_descriptors.py, django/db/models/fields/related_lookups.py, django/db/models/fields/files.py, django/contrib/gis/db/models/fields.py, django/db/models/fields/mixins.py, django/db/migrations/operations/fields.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12184 — django/django
- Gold: `django/urls/resolvers.py`
- Predicted: `django/core/handlers/exception.py, django/core/handlers/base.py, django/contrib/staticfiles/handlers.py, django/core/management/base.py, django/urls/base.py, django/views/generic/base.py, django/contrib/staticfiles/views.py, django/core/handlers/asgi.py, django/core/serializers/json.py, django/core/files/base.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12470 — django/django
- Gold: `django/db/models/sql/compiler.py`
- Predicted: `django/db/models/sql/query.py, django/db/models/deletion.py, django/db/models/options.py, django/db/models/fields/related.py, django/db/models/query.py, django/db/models/expressions.py, django/db/models/sql/datastructures.py, django/db/models/manager.py, django/db/models/query_utils.py, django/db/models/sql/where.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12747 — django/django
- Gold: `django/db/models/deletion.py`
- Predicted: `tests/queryset_pickle/tests.py, tests/expressions/test_queryset_values.py, tests/queryset_pickle/models.py, django/contrib/sessions/backends/file.py, django/db/models/query.py, django/db/models/fields/files.py, django/test/testcases.py, tests/model_regress/tests.py, django/utils/autoreload.py, tests/admin_views/test_autocomplete_view.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12856 — django/django
- Gold: `django/db/models/base.py`
- Predicted: `django/db/models/fields/related.py, django/db/models/fields/json.py, django/db/models/fields/files.py, django/db/models/constraints.py, django/db/models/fields/mixins.py, django/db/models/fields/related_lookups.py, django/contrib/gis/db/models/fields.py, django/core/management/commands/diffsettings.py, django/db/models/fields/related_descriptors.py, django/db/models/fields/__init__.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12908 — django/django
- Gold: `django/db/models/query.py`
- Predicted: `js_tests/admin/SelectFilter2.test.js, django/contrib/admin/static/admin/js/SelectFilter2.js, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py, django/contrib/admin/filters.py, django/contrib/auth/management/commands/createsuperuser.py, django/contrib/auth/migrations/0012_alter_user_first_name_max_length.py, django/contrib/auth/migrations/0004_alter_user_username_opts.py, django/contrib/auth/migrations/0008_alter_user_username_max_length.py, django/contrib/admin/widgets.py, js_tests/admin/SelectBox.test.js`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-13033 — django/django
- Gold: `django/db/models/sql/compiler.py`
- Predicted: `django/db/models/query.py, django/db/models/fields/related_lookups.py, django/db/models/query_utils.py, django/db/models/sql/query.py, tests/model_fields/test_foreignkey.py, django/db/models/sql/datastructures.py, tests/foreign_object/models/empty_join.py, django/db/models/fields/__init__.py, django/db/models/sql/subqueries.py, django/db/models/fields/json.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-13158 — django/django
- Gold: `django/db/models/sql/query.py`
- Predicted: `tests/model_forms/test_modelchoicefield.py, django/forms/models.py, django/db/models/fields/files.py, django/db/models/fields/related_lookups.py, django/db/models/fields/related_descriptors.py, tests/model_fields/test_manytomanyfield.py, tests/queryset_pickle/models.py, tests/foreign_object/models/article.py, tests/model_package/models/article.py, tests/model_package/models/publication.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-13265 — django/django
- Gold: `django/db/migrations/autodetector.py`
- Predicted: `django/db/models/fields/related.py, django/db/models/indexes.py, django/contrib/gis/db/models/fields.py, tests/migrations/test_autodetector.py, tests/migrations/test_operations.py, django/core/management/commands/makemigrations.py, tests/gis_tests/gis_migrations/test_operations.py, django/db/migrations/loader.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/contrib/auth/migrations/0002_alter_permission_name_max_length.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-13315 — django/django
- Gold: `django/forms/models.py`
- Predicted: `tests/model_fields/test_foreignkey.py, django/contrib/admin/migrations/0003_logentry_add_action_flag_choices.py, django/contrib/admin/options.py, django/db/models/options.py, tests/foreign_object/models/empty_join.py, tests/nested_foreign_keys/tests.py, tests/foreign_object/test_empty_join.py, tests/model_fields/tests.py, tests/auth_tests/models/with_foreign_key.py, tests/migrations/test_operations.py`
- Recall@10: **0.000**, Hit@10: **0**
