# mcp-brain SWE-bench Lite benchmark report

## Summary

- Instances evaluated: **2294**
- Errors: **5**
- Avg gold files: **1.66**
- Avg predicted files: **9.98**

| Metric | @1 | @3 | @5 | @10 |
|---|---:|---:|---:|---:|
| Hit | 0.245 | 0.434 | 0.537 | 0.634 |
| Recall | 0.201 | 0.366 | 0.461 | 0.558 |
| MAP | 0.245 | 0.284 | 0.304 | 0.318 |

## Worst misses / examples

### astropy__astropy-12544 — astropy/astropy
- Gold: `astropy/io/fits/connect.py`
- Predicted: `astropy/table/groups.py, astropy/io/misc/asdf/tags/table/table.py, astropy/table/table.py, astropy/io/fits/hdu/table.py, astropy/io/votable/table.py, astropy/io/fits/column.py, astropy/cosmology/io/table.py, astropy/table/tests/test_masked.py, astropy/table/column.py, astropy/utils/masked/function_helpers.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-12842 — astropy/astropy
- Gold: `astropy/time/core.py, astropy/time/formats.py`
- Predicted: `astropy/timeseries/binned.py, astropy/io/ascii/ecsv.py, astropy/io/fits/column.py, astropy/cosmology/io/ecsv.py, astropy/io/misc/asdf/tags/time/time.py, astropy/timeseries/core.py, astropy/table/column.py, astropy/timeseries/downsample.py, astropy/visualization/time.py, astropy/io/registry/core.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-13075 — astropy/astropy
- Gold: `astropy/cosmology/io/__init__.py, astropy/cosmology/io/html.py`
- Predicted: `astropy/io/votable/validator/html.py, astropy/io/votable/table.py, astropy/table/table.py, astropy/io/fits/hdu/table.py, astropy/cosmology/io/table.py, astropy/io/ascii/html.py, astropy/units/format/fits.py, astropy/cosmology/parameter.py, astropy/units/format/ogip.py, astropy/io/misc/asdf/tags/table/table.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-13132 — astropy/astropy
- Gold: `astropy/time/core.py, astropy/time/time_helper/__init__.py, astropy/time/time_helper/function_helpers.py`
- Predicted: `astropy/io/votable/validator/html.py, astropy/timeseries/binned.py, astropy/visualization/time.py, astropy/io/misc/asdf/tags/time/time.py, astropy/timeseries/io/kepler.py, astropy/timeseries/periodograms/bls/setup_package.py, astropy/timeseries/sampled.py, astropy/time/setup_package.py, astropy/io/ascii/html.py, astropy/io/misc/asdf/tags/time/timedelta.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-13438 — astropy/astropy
- Gold: `astropy/table/jsviewer.py`
- Predicted: `astropy/io/votable/validator/html.py, astropy/extern/jquery/data/js/jquery-3.1.1.min.js, astropy/extern/jquery/data/js/jquery-3.1.1.js, astropy/io/ascii/ecsv.py, astropy/coordinates/solar_system.py, astropy/io/ascii/html.py, astropy/extern/jquery/data/js/jquery.dataTables.js, astropy/extern/jquery/data/js/jquery.dataTables.min.js, astropy/utils/compat/numpycompat.py, astropy/version.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-13453 — astropy/astropy
- Gold: `astropy/io/ascii/html.py`
- Predicted: `astropy/table/scripts/showtable.py, astropy/table/table.py, astropy/io/ascii/mrt.py, astropy/table/pprint.py, astropy/io/votable/validator/html.py, astropy/io/fits/hdu/table.py, astropy/io/votable/table.py, astropy/table/groups.py, astropy/table/meta.py, astropy/cosmology/io/table.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-13462 — astropy/astropy
- Gold: `astropy/time/utils.py`
- Predicted: `astropy/time/tests/test_precision.py, astropy/io/fits/tests/test_fitstime.py, astropy/io/fits/fitstime.py, astropy/coordinates/tests/test_celestial_transformations.py, astropy/io/ascii/tests/test_cds.py, astropy/convolution/tests/test_convolve_kernels.py, .pyinstaller/run_astropy_tests.py, astropy/coordinates/tests/test_arrays.py, astropy/timeseries/downsample.py, astropy/io/ascii/tests/test_read.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-13465 — astropy/astropy
- Gold: `astropy/io/fits/diff.py, astropy/utils/diff.py`
- Predicted: `astropy/io/fits/scripts/fitsdiff.py, astropy/io/fits/hdu/hdulist.py, astropy/io/fits/hdu/base.py, astropy/io/fits/hdu/table.py, astropy/io/misc/asdf/extension.py, astropy/io/fits/hdu/image.py, astropy/io/fits/hdu/compressed.py, astropy/io/fits/column.py, astropy/io/misc/asdf/tags/fits/fits.py, astropy/io/fits/hdu/groups.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14182 — astropy/astropy
- Gold: `astropy/io/ascii/rst.py`
- Predicted: `astropy/units/core.py, astropy/units/__init__.py, astropy/units/function/core.py, astropy/table/__init__.py, astropy/utils/xml/writer.py, astropy/units/format/__init__.py, astropy/table/connect.py, astropy/units/function/__init__.py, astropy/units/quantity_helper/__init__.py, astropy/io/ascii/__init__.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14439 — astropy/astropy
- Gold: `astropy/modeling/physical_models.py, astropy/units/format/generic.py`
- Predicted: `astropy/units/format/fits.py, astropy/io/fits/_tiled_compression/tiled_compression.py, astropy/io/misc/asdf/tags/fits/fits.py, astropy/io/fits/hdu/compressed.py, astropy/io/fits/_tiled_compression/setup_package.py, astropy/io/fits/_tiled_compression/codecs.py, astropy/io/fits/_tiled_compression/quantization.py, astropy/io/fits/_tiled_compression/__init__.py, astropy/timeseries/tests/test_sampled.py, astropy/io/fits/_tiled_compression/src/compression.c`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14528 — astropy/astropy
- Gold: `astropy/io/fits/hdu/image.py`
- Predicted: `astropy/io/misc/asdf/tags/fits/fits.py, astropy/io/fits/hdu/base.py, astropy/io/fits/hdu/streaming.py, astropy/io/fits/hdu/compressed.py, astropy/io/fits/hdu/groups.py, astropy/io/fits/hdu/hdulist.py, astropy/io/fits/__init__.py, astropy/io/fits/hdu/__init__.py, astropy/io/fits/hdu/nonstandard.py, astropy/io/fits/convenience.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14539 — astropy/astropy
- Gold: `astropy/io/fits/diff.py`
- Predicted: `astropy/io/fits/hdu/table.py, astropy/table/column.py, astropy/io/fits/hdu/hdulist.py, astropy/io/fits/hdu/base.py, astropy/io/fits/scripts/fitsdiff.py, astropy/io/fits/column.py, astropy/units/format/fits.py, astropy/io/misc/asdf/tags/fits/fits.py, astropy/io/fits/hdu/image.py, astropy/io/misc/asdf/extension.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14566 — astropy/astropy
- Gold: `astropy/time/formats.py`
- Predicted: `astropy/units/format/cds.py, astropy/units/format/ogip.py, astropy/units/format/generic.py, astropy/units/format/utils.py, astropy/coordinates/transformations.py, astropy/units/quantity_helper/function_helpers.py, astropy/coordinates/spectral_quantity.py, astropy/units/quantity.py, astropy/units/format/console.py, astropy/coordinates/angle_formats.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14701 — astropy/astropy
- Gold: `astropy/cosmology/io/__init__.py, astropy/cosmology/io/latex.py`
- Predicted: `astropy/cosmology/io/html.py, astropy/io/votable/table.py, astropy/cosmology/io/table.py, astropy/io/ascii/latex.py, astropy/io/fits/hdu/table.py, astropy/cosmology/io/tests/test_html.py, astropy/table/table.py, astropy/cosmology/io/tests/test_table.py, astropy/io/votable/validator/html.py, astropy/cosmology/funcs/comparison.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14907 — astropy/astropy
- Gold: `astropy/table/index.py, astropy/time/core.py`
- Predicted: `astropy/table/tests/test_groups.py, astropy/table/groups.py, astropy/io/fits/tests/test_groups.py, astropy/io/fits/hdu/groups.py, astropy/utils/masked/core.py, astropy/io/fits/hdu/table.py, astropy/table/column.py, astropy/table/sorted_array.py, astropy/cosmology/io/table.py, astropy/table/ndarray_mixin.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-8005 — astropy/astropy
- Gold: `astropy/units/equivalencies.py`
- Predicted: `astropy/cosmology/funcs.py, astropy/cosmology/core.py, astropy/cosmology/__init__.py, astropy/cosmology/parameters.py, astropy/utils/compat/misc.py, astropy/nddata/compat.py, astropy/io/misc/asdf/tags/transform/compound.py, astropy/utils/compat/funcsigs.py, astropy/utils/compat/__init__.py, astropy/utils/compat/futures/__init__.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-8519 — astropy/astropy
- Gold: `astropy/units/function/core.py`
- Predicted: `astropy/units/function/magnitude_zero_points.py, astropy/units/function/logarithmic.py, astropy/units/quantity.py, astropy/units/quantity_helper/converters.py, astropy/units/astrophys.py, astropy/units/photometric.py, astropy/units/quantity_helper/helpers.py, astropy/units/equivalencies.py, astropy/units/si.py, astropy/units/cds.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-10087 — django/django
- Gold: `django/core/management/commands/sqlmigrate.py`
- Predicted: `django/core/management/commands/makemigrations.py, django/core/management/commands/squashmigrations.py, django/core/management/commands/showmigrations.py, tests/migrations/test_migrations_squashed_complex_multi_apps/app2/1_auto.py, tests/migrations/test_migrations_squashed_complex_multi_apps/app1/3_auto.py, tests/migrations/test_migrations_squashed_complex_multi_apps/app2/2_auto.py, tests/migrations/test_migrations_squashed_complex_multi_apps/app1/2_auto.py, tests/migrations/test_migrations_squashed_complex_multi_apps/app1/4_auto.py, tests/migrations/test_migrations_squashed_complex_multi_apps/app2/1_squashed_2.py, tests/migrations/test_migrations_squashed_complex_multi_apps/app1/1_auto.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-10097 — django/django
- Gold: `django/core/validators.py`
- Predicted: `django/core/checks/urls.py, django/contrib/auth/urls.py, django/contrib/flatpages/urls.py, django/contrib/admindocs/urls.py, django/contrib/staticfiles/urls.py, django/contrib/auth/password_validation.py, tests/user_commands/urls.py, tests/middleware/urls.py, tests/timezones/urls.py, tests/middleware_exceptions/urls.py`
- Recall@10: **0.000**, Hit@10: **0**

### django__django-10213 — django/django
- Gold: `django/core/management/base.py, django/core/management/color.py`
- Predicted: `django/contrib/staticfiles/management/commands/runserver.py, django/contrib/staticfiles/management/commands/collectstatic.py, django/core/management/commands/loaddata.py, django/core/management/commands/sendtestemail.py, django/core/management/commands/runserver.py, django/core/management/commands/inspectdb.py, django/core/management/commands/dumpdata.py, django/core/management/commands/makemigrations.py, django/core/management/commands/sqlmigrate.py, django/core/management/commands/flush.py`
- Recall@10: **0.000**, Hit@10: **0**
