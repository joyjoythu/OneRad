"""Local copy of the radiomics feature extractor.

This module was copied from ``reference_code/DONGGUAN_NEW_Radiomic/Atsea_def.py``
so that the application no longer depends on external reference code paths.
Only the ``cir_get_features`` function is kept here.
"""

from radiomics import featureextractor as FEE


def cir_get_features(image_filepath: str, mask_filepath: str, yaml_path: str) -> dict:
    """Extract radiomics features using PyRadiomics with a YAML config file.

    Parameters
    ----------
    image_filepath : str
        Path to the medical image (e.g. NIfTI file).
    mask_filepath : str
        Path to the corresponding mask.
    yaml_path : str
        Path to the PyRadiomics YAML parameter file.

    Returns
    -------
    dict
        Mapping from feature name to float value. Diagnostic features are
        excluded.
    """
    extractor = FEE.RadiomicsFeatureExtractor(yaml_path)
    result = extractor.execute(image_filepath, mask_filepath)
    feature = {}
    for key in result.keys():
        if "diagnostics" not in key:
            feature[key] = float(result[key])
    return feature
