# mcp-brain SWE-bench Lite benchmark report

## Summary

- Instances evaluated: **5**
- Errors: **0**
- Avg gold files: **1.00**
- Avg predicted files: **10.00**

| Metric | @1 | @3 | @5 | @10 |
|---|---:|---:|---:|---:|
| Hit | 0.000 | 0.000 | 0.000 | 0.400 |
| Recall | 0.000 | 0.000 | 0.000 | 0.400 |
| MAP | 0.000 | 0.000 | 0.000 | 0.047 |

## Worst misses / examples

### astropy__astropy-14182 — astropy/astropy
- Gold: `astropy/io/ascii/rst.py`
- Predicted: `astropy/units/format/cds.py, astropy/units/format/generic.py, astropy/units/format/ogip.py, astropy/units/format/fits.py, astropy/units/format/vounit.py, astropy/units/function/core.py, astropy/units/format/utils.py, astropy/units/tests/test_format.py, astropy/units/core.py, astropy/units/__init__.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-14365 — astropy/astropy
- Gold: `astropy/io/ascii/qdp.py`
- Predicted: `astropy/io/ascii/tests/test_html.py, astropy/io/ascii/tests/test_c_reader.py, astropy/io/ascii/tests/test_cds_header_from_readme.py, astropy/io/ascii/tests/test_types.py, astropy/io/ascii/tests/test_qdp.py, astropy/table/tests/test_pprint.py, astropy/io/ascii/tests/test_cds.py, astropy/io/ascii/tests/test_write.py, astropy/table/tests/test_column.py, astropy/samp/lockfile_helpers.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-6938 — astropy/astropy
- Gold: `astropy/io/fits/fitsrec.py`
- Predicted: `astropy/io/fits/tests/test_table.py, astropy/io/fits/tests/test_checksum.py, astropy/io/fits/tests/test_image.py, astropy/io/fits/tests/__init__.py, astropy/io/fits/tests/test_core.py, astropy/table/tests/test_operations.py, astropy/io/fits/tests/test_uint.py, astropy/io/fits/tests/test_header.py, astropy/io/fits/tests/test_compression_failures.py, astropy/coordinates/tests/test_atc_replacements.py`
- Recall@10: **0.000**, Hit@10: **0**

### astropy__astropy-12907 — astropy/astropy
- Gold: `astropy/modeling/separable.py`
- Predicted: `astropy/modeling/tests/test_separable.py, astropy/modeling/tests/test_models_quantities.py, astropy/modeling/tests/test_compound.py, astropy/modeling/functional_models.py, astropy/modeling/tests/test_physical_models.py, astropy/modeling/tests/test_models.py, astropy/modeling/tests/test_functional_models.py, astropy/modeling/models.py, astropy/modeling/separable.py, astropy/modeling/tests/test_quantities_evaluation.py`
- Recall@10: **1.000**, Hit@10: **1**

### astropy__astropy-14995 — astropy/astropy
- Gold: `astropy/nddata/mixins/ndarithmetic.py`
- Predicted: `astropy/nddata/mixins/tests/test_ndarithmetic.py, astropy/nddata/compat.py, astropy/nddata/tests/test_bitmask.py, astropy/nddata/bitmask.py, astropy/nddata/nddata_withmixins.py, astropy/nddata/nduncertainty.py, astropy/nddata/tests/test_nduncertainty.py, astropy/nddata/mixins/ndarithmetic.py, astropy/coordinates/errors.py, astropy/constants/tests/test_prior_version.py`
- Recall@10: **1.000**, Hit@10: **1**
