import os
import shutil

import numpy as np
import SimpleITK as sitk


def convert_patient_sequences(
    root_dir: str,
    images_root: str,
    masks_root: str,
    category: str
) -> None:
    """
    处理某个大类目录下的所有病例。

    输出结构保持原目录层级：
      images_root/category/patient/seq.nii.gz
      masks_root/category/patient/seq.nii.gz
    """
    category_path = os.path.join(root_dir, category)
    if not os.path.isdir(category_path):
        print(f"[跳过] 目录不存在: {category_path}")
        return

    patient_dirs = [d for d in os.listdir(category_path)
                    if os.path.isdir(os.path.join(category_path, d))]
    patient_dirs.sort()

    for patient in patient_dirs:
        patient_path = os.path.join(category_path, patient)
        seq_dirs = [d for d in os.listdir(patient_path)
                    if os.path.isdir(os.path.join(patient_path, d))]
        seq_dirs.sort()

        for seq in seq_dirs:
            seq_path = os.path.join(patient_path, seq)

            # 收集文件
            dcm_files = [f for f in os.listdir(seq_path)
                         if f.lower().endswith('.dcm')]
            niigz_files = [f for f in os.listdir(seq_path)
                           if f.lower().endswith('.nii.gz')]
            nii_files = [f for f in os.listdir(seq_path)
                         if f.lower().endswith('.nii') and not f.lower().endswith('.nii.gz')]

            # 输出路径保持原结构
            rel_dir = os.path.join(category, patient)
            image_out_dir = os.path.join(images_root, rel_dir)
            mask_out_dir = os.path.join(masks_root, rel_dir)
            os.makedirs(image_out_dir, exist_ok=True)
            os.makedirs(mask_out_dir, exist_ok=True)

            # 输出文件名直接用序列名
            image_out = os.path.join(image_out_dir, f"{seq}.nii.gz")
            mask_out = os.path.join(mask_out_dir, f"{seq}.nii.gz")

            has_image = False
            has_mask = False
            image_source_type = None  # 'dcm', 'nifti'

            # ---- 处理原图 ----
            if dcm_files:
                # 有 DICOM，转换为 nii.gz
                try:
                    reader = sitk.ImageSeriesReader()
                    dicom_names = reader.GetGDCMSeriesFileNames(seq_path)
                    if len(dicom_names) == 0:
                        print(f"[警告] SimpleITK 未找到 DICOM 序列，跳过: {seq_path}")
                        continue
                    reader.SetFileNames(dicom_names)
                    image = reader.Execute()
                    sitk.WriteImage(image, image_out)
                    print(f"[原图-DICOM] {category}/{patient}/{seq}")
                    has_image = True
                    image_source_type = 'dcm'
                except Exception as e:
                    print(f"[错误] DICOM 转换失败: {seq_path} -> {e}")
                    continue
            elif niigz_files or nii_files:
                # 无 DICOM，通过是否二值来区分原图和 mask
                candidates = []
                for f in niigz_files:
                    candidates.append((os.path.join(seq_path, f), f, 'niigz'))
                for f in nii_files:
                    candidates.append((os.path.join(seq_path, f), f, 'nii'))

                image_candidate = None   # (src_path, filename, ftype, sitk_img)
                mask_candidate = None

                for src_path, filename, ftype in candidates:
                    try:
                        img = sitk.ReadImage(src_path)
                    except Exception as e:
                        print(f"[警告] 读取文件失败，跳过: {src_path} -> {e}")
                        continue

                    arr = sitk.GetArrayFromImage(img)
                    unique_vals = np.unique(arr)

                    if len(unique_vals) <= 2:
                        # 二值文件 -> mask 候选
                        if mask_candidate is None:
                            mask_candidate = (src_path, filename, ftype, img)
                    else:
                        # 非二值文件 -> 原图候选
                        if image_candidate is None:
                            image_candidate = (src_path, filename, ftype, img)

                    if image_candidate is not None and mask_candidate is not None:
                        break

                # 保存原图（重命名为 seq.nii.gz）
                if image_candidate is not None:
                    src_path, filename, ftype, img = image_candidate
                    try:
                        if ftype == 'nii':
                            sitk.WriteImage(img, image_out)
                            print(f"[原图-NII]    {category}/{patient}/{seq} <- {filename} (已转为 .nii.gz)")
                        else:
                            shutil.copy2(src_path, image_out)
                            print(f"[原图-COPY]   {category}/{patient}/{seq} <- {filename}")
                        has_image = True
                        image_source_type = 'nifti'
                    except Exception as e:
                        print(f"[错误] 保存原图失败: {src_path} -> {e}")
                        continue
                else:
                    print(f"[跳过] 无法识别原图（无非二值文件）: {seq_path}")
                    continue

                # 保存 mask（重命名为 seq.nii.gz）
                if mask_candidate is not None:
                    src_path, filename, ftype, img = mask_candidate
                    try:
                        if ftype == 'nii':
                            sitk.WriteImage(img, mask_out)
                            print(f"[Mask-NII]    {category}/{patient}/{seq} <- {filename} (已转为 .nii.gz)")
                        else:
                            shutil.copy2(src_path, mask_out)
                            print(f"[Mask]        {category}/{patient}/{seq} <- {filename}")
                        has_mask = True
                    except Exception as e:
                        print(f"[错误] 保存 Mask 失败: {src_path} -> {e}")
            else:
                print(f"[跳过] 无图像文件: {seq_path}")
                continue

            # ---- 处理 Mask ----
            # 策略：有 dcm 时，目录里的 .nii.gz 或 .nii 就是 mask
            if image_source_type == 'dcm':
                if niigz_files:
                    src_mask = os.path.join(seq_path, niigz_files[0])
                    try:
                        shutil.copy2(src_mask, mask_out)
                        print(f"[Mask]        {category}/{patient}/{seq} <- {niigz_files[0]}")
                        has_mask = True
                    except Exception as e:
                        print(f"[错误] 复制 Mask 失败: {src_mask} -> {e}")
                elif nii_files:
                    src_mask = os.path.join(seq_path, nii_files[0])
                    try:
                        img = sitk.ReadImage(src_mask)
                        sitk.WriteImage(img, mask_out)
                        print(f"[Mask-NII]    {category}/{patient}/{seq} <- {nii_files[0]} (已转为 .nii.gz)")
                        has_mask = True
                    except Exception as e:
                        print(f"[错误] 读取 .nii Mask 失败: {src_mask} -> {e}")

            if not has_mask and has_image:
                print(f"[无Mask]      {category}/{patient}/{seq}")


def main():
    # 数据根目录（脚本所在目录）
    data_root = r'Z:\data\huyilan2025\tm4.16\tm'

    # 输出目录
    output_root = os.path.join(data_root, "1output")
    images_root = os.path.join(output_root, "images")
    masks_root = os.path.join(output_root, "masks")

    # 要处理的三个大类目录
    categories = ["jx1", "cj2", "wu3"]

    for category in categories:
        print(f"\n========== 开始处理: {category} ==========")
        convert_patient_sequences(data_root, images_root, masks_root, category)

    print("\n========== 全部处理完成 ==========")


if __name__ == "__main__":
    main()
