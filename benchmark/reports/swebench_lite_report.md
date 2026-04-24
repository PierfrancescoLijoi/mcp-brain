# mcp-brain SWE-bench Lite benchmark report

## Summary

- Instances evaluated: **30**
- Errors: **0**
- Avg gold files: **1.00**
- Avg predicted files: **10.00**

| Metric | @1 | @3 | @5 | @10 |
|---|---:|---:|---:|---:|
| Hit | 0.200 | 0.400 | 0.433 | 0.567 |
| Recall | 0.200 | 0.400 | 0.433 | 0.567 |
| MAP | 0.200 | 0.289 | 0.296 | 0.313 |

## Worst misses / examples

### django__django-10914 — django/django
- Gold: `django/conf/global_settings.py`
- Predicted: `django/contrib/sessions/backends/file.py, django/core/files/storage.py, django/contrib/staticfiles/storage.py, django/contrib/staticfiles/management/commands/collectstatic.py, tests/file_uploads/tests.py, django/core/files/uploadhandler.py, django/core/files/uploadedfile.py, django/contrib/staticfiles/handlers.py, django/contrib/auth/migrations/0011_update_proxy_permissions.py, django/contrib/staticfiles/finders.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11001 — django/django
- Gold: `django/db/models/sql/compiler.py`
- Predicted: `django/core/management/sql.py, django/db/backends/mysql/compiler.py, django/contrib/postgres/search.py, django/db/models/functions/datetime.py, tests/forms_tests/widget_tests/test_splithiddendatetimewidget.py, django/db/backends/postgresql/introspection.py, django/contrib/gis/db/backends/mysql/introspection.py, django/db/backends/mysql/operations.py, django/db/backends/mysql/introspection.py, django/db/backends/sqlite3/introspection.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11039 — django/django
- Gold: `django/core/management/commands/sqlmigrate.py`
- Predicted: `tests/migrations/test_commands.py, tests/gis_tests/gis_migrations/test_commands.py, django/core/management/commands/makemigrations.py, django/db/migrations/executor.py, django/core/management/commands/showmigrations.py, tests/migrations/test_operations.py, tests/gis_tests/gis_migrations/test_operations.py, django/core/management/commands/squashmigrations.py, tests/staticfiles_tests/test_management.py, tests/admin_scripts/tests.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11049 — django/django
- Gold: `django/db/models/fields/__init__.py`
- Predicted: `django/db/models/functions/text.py, tests/forms_tests/field_tests/test_durationfield.py, django/contrib/postgres/fields/array.py, django/contrib/postgres/fields/ranges.py, django/db/models/fields/related.py, django/utils/text.py, tests/model_fields/test_durationfield.py, django/template/backends/django.py, django/contrib/postgres/fields/citext.py, django/forms/fields.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11564 — django/django
- Gold: `django/conf/__init__.py`
- Predicted: `django/contrib/staticfiles/management/commands/collectstatic.py, django/contrib/staticfiles/management/commands/findstatic.py, django/contrib/staticfiles/finders.py, django/contrib/staticfiles/urls.py, django/contrib/staticfiles/checks.py, django/contrib/staticfiles/management/commands/runserver.py, django/contrib/staticfiles/views.py, django/contrib/staticfiles/apps.py, django/contrib/staticfiles/utils.py, django/contrib/staticfiles/storage.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11583 — django/django
- Gold: `django/utils/autoreload.py`
- Predicted: `django/core/management/commands/runserver.py, django/core/management/__init__.py, django/contrib/staticfiles/management/commands/findstatic.py, django/contrib/staticfiles/management/commands/runserver.py, django/core/management/commands/startproject.py, django/core/management/commands/startapp.py, django/contrib/staticfiles/management/commands/collectstatic.py, django/db/models/fields/files.py, django/core/management/commands/showmigrations.py, django/core/management/commands/check.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11630 — django/django
- Gold: `django/core/checks/model_checks.py`
- Predicted: `django/contrib/gis/db/backends/spatialite/base.py, django/db/backends/base/base.py, django/contrib/gis/db/backends/postgis/base.py, django/db/backends/sqlite3/base.py, django/db/models/base.py, django/core/cache/backends/base.py, django/contrib/sessions/backends/base.py, django/db/backends/postgresql/base.py, django/template/backends/base.py, django/db/backends/dummy/base.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11742 — django/django
- Gold: `django/db/models/fields/__init__.py`
- Predicted: `tests/migrations/test_writer.py, django/db/migrations/loader.py, tests/migrations/test_base.py, tests/migrations/test_operations.py, tests/gis_tests/gis_migrations/test_operations.py, django/core/management/commands/makemigrations.py, django/contrib/auth/migrations/0002_alter_permission_name_max_length.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/contrib/auth/migrations/0003_alter_user_email_max_length.py, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11797 — django/django
- Gold: `django/db/models/lookups.py`
- Predicted: `django/contrib/auth/migrations/0003_alter_user_email_max_length.py, tests/migrations/test_operations.py, django/core/management/commands/makemigrations.py, tests/migrations/test_writer.py, tests/migrations/test_base.py, django/db/migrations/loader.py, tests/gis_tests/gis_migrations/test_operations.py, django/contrib/auth/migrations/0005_alter_user_last_login_null.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11815 — django/django
- Gold: `django/db/migrations/serializer.py`
- Predicted: `django/db/migrations/operations/models.py, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py, django/contrib/auth/migrations/0002_alter_permission_name_max_length.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/contrib/auth/migrations/0008_alter_user_username_max_length.py, tests/migrations/test_base.py, tests/migrations/test_operations.py, django/core/management/commands/makemigrations.py, tests/gis_tests/gis_migrations/test_operations.py, tests/migrations/test_writer.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11910 — django/django
- Gold: `django/db/migrations/autodetector.py`
- Predicted: `django/db/migrations/loader.py, tests/migrations/test_writer.py, tests/migrations/test_base.py, tests/gis_tests/gis_migrations/test_operations.py, django/core/management/commands/makemigrations.py, tests/migrations/test_operations.py, django/contrib/auth/migrations/0009_alter_user_last_name_max_length.py, django/contrib/auth/migrations/0010_alter_group_name_max_length.py, django/contrib/auth/migrations/0002_alter_permission_name_max_length.py, django/contrib/auth/migrations/0008_alter_user_username_max_length.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-11964 — django/django
- Gold: `django/db/models/enums.py`
- Predicted: `django/db/models/fields/reverse_related.py, django/db/models/fields/related_descriptors.py, django/db/models/fields/__init__.py, django/db/models/fields/related.py, django/db/models/functions/text.py, django/db/models/fields/related_lookups.py, django/db/models/constraints.py, django/db/models/fields/files.py, django/db/models/fields/mixins.py, django/db/models/manager.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-12113 — django/django
- Gold: `django/db/backends/sqlite3/creation.py`
- Predicted: `django/contrib/gis/db/backends/spatialite/base.py, django/db/backends/sqlite3/base.py, django/db/models/sql/compiler.py, django/db/backends/postgresql/base.py, django/db/backends/mysql/base.py, django/contrib/gis/db/backends/postgis/base.py, django/db/backends/sqlite3/operations.py, django/db/models/base.py, django/db/migrations/operations/base.py, django/contrib/gis/db/backends/mysql/base.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-12907 — astropy/astropy
- Gold: `astropy/modeling/separable.py`
- Predicted: `astropy/modeling/tests/test_separable.py, astropy/modeling/separable.py, astropy/modeling/rotations.py, astropy/modeling/polynomial.py, astropy/modeling/spline.py, astropy/modeling/models.py, astropy/modeling/functional_models.py, astropy/modeling/tests/test_models.py, astropy/modeling/physical_models.py, astropy/modeling/math_functions.py`
- Recall@10: **1.000**, Hit@10: **1**

### astropy__astropy-14182 — astropy/astropy
- Gold: `astropy/io/ascii/rst.py`
- Predicted: `astropy/units/core.py, astropy/units/function/core.py, astropy/units/__init__.py, astropy/utils/xml/writer.py, astropy/units/format/__init__.py, astropy/table/__init__.py, astropy/units/function/__init__.py, astropy/table/connect.py, astropy/units/quantity_helper/__init__.py, astropy/io/ascii/rst.py`
- Recall@10: **1.000**, Hit@10: **1**

### astropy__astropy-14365 — astropy/astropy
- Gold: `astropy/io/ascii/qdp.py`
- Predicted: `astropy/io/ascii/qdp.py, astropy/io/fits/hdu/table.py, astropy/table/scripts/showtable.py, astropy/io/votable/table.py, astropy/table/table_helpers.py, astropy/table/table.py, astropy/io/misc/asdf/tags/table/table.py, astropy/cosmology/io/table.py, astropy/table/connect.py, astropy/table/__init__.py`
- Recall@10: **1.000**, Hit@10: **1**

### astropy__astropy-14995 — astropy/astropy
- Gold: `astropy/nddata/mixins/ndarithmetic.py`
- Predicted: `astropy/nddata/__init__.py, astropy/nddata/compat.py, astropy/nddata/tests/test_bitmask.py, astropy/nddata/bitmask.py, astropy/nddata/utils.py, astropy/nddata/nduncertainty.py, astropy/nddata/nddata.py, astropy/nddata/ccddata.py, astropy/nddata/nddata_withmixins.py, astropy/nddata/mixins/ndarithmetic.py`
- Recall@10: **1.000**, Hit@10: **1**

### astropy__astropy-6938 — astropy/astropy
- Gold: `astropy/io/fits/fitsrec.py`
- Predicted: `astropy/io/fits/fitsrec.py, astropy/io/fits/hdu/compressed.py, astropy/io/fits/hdu/table.py, astropy/io/fits/connect.py, astropy/io/fits/fitstime.py, astropy/units/format/fits.py, astropy/io/fits/hdu/groups.py, astropy/io/fits/util.py, astropy/io/fits/convenience.py, astropy/io/fits/header.py`
- Recall@10: **1.000**, Hit@10: **1**

### astropy__astropy-7746 — astropy/astropy
- Gold: `astropy/wcs/wcs.py`
- Predicted: `astropy/visualization/wcsaxes/transforms.py, cextern/wcslib/C/wcs.c, astropy/wcs/wcs.py, cextern/wcslib/C/wcs.h, astropy/wcs/_docutil.py, astropy/wcs/docstrings.py, astropy/wcs/src/str_list_proxy.c, astropy/wcs/src/wcslib_wrap.c, astropy/wcs/src/unit_list_proxy.c, astropy/wcs/src/wcslib_tabprm_wrap.c`
- Recall@10: **1.000**, Hit@10: **1**

### django__django-10924 — django/django
- Gold: `django/db/models/fields/__init__.py`
- Predicted: `django/db/models/fields/related_descriptors.py, django/db/models/fields/reverse_related.py, django/db/models/fields/related_lookups.py, django/db/models/fields/related.py, django/db/models/fields/files.py, django/db/models/fields/__init__.py, django/db/migrations/operations/models.py, django/db/models/manager.py, django/db/models/fields/proxy.py, django/db/models/fields/mixins.py`
- Recall@10: **1.000**, Hit@10: **1**
