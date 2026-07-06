import os
import shutil
import csv
import SimpleITK as sitk
import numpy as np


def copy_failed_cases(
    failed_csv_path,
    img_root,
    mask_root,
    review_root,
):
    """
    读取 failed_cases.csv，将有问题的 image 和 mask 复制到单独目录便于检查。
    同时按错误类型分类，并给出处理建议。
    """
    if not os.path.exists(failed_csv_path):
        print(f"[!] 失败记录不存在: {failed_csv_path}")
        return

    # 创建审查根目录
    judgedir(review_root)

    review_img_root = os.path.join(review_root, 'images')
    review_mask_root = os.path.join(review_root, 'masks')
    review_combined_root = os.path.join(review_root, 'combined')

    # 读取失败记录
    failed_records = []
    with open(failed_csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            failed_records.append(row)

    if not failed_records:
        print("[✓] 没有失败记录需要处理。")
        return

    # 分类统计
    type_counts = {}
    for rec in failed_records:
        reason = rec['reason']
        # 提取错误类型关键词
        if 'only contains 1 segmented voxel' in reason:
            err_type = 'single_voxel'
        elif 'No label object with label 1' in reason:
            err_type = 'no_label_1'
        elif 'too few dimensions' in reason:
            err_type = 'low_dimensions'
        else:
            err_type = 'other'

        rec['err_type'] = err_type
        type_counts[err_type] = type_counts.get(err_type, 0) + 1

    # 复制文件
    copied = 0
    for rec in failed_records:
        phase = rec['phase']
        case = rec['case']
        seq = rec['sequence']
        img_path = rec['img_path']
        mask_path = rec['mask_path']
        reason = rec['reason']
        err_type = rec['err_type']

        # ===== 第一遍：保留原来的分开目录结构，但命名保持原命名 =====
        dst_img_dir = os.path.join(review_img_root, phase, case)
        dst_mask_dir = os.path.join(review_mask_root, phase, case)
        judgedir(dst_img_dir)
        judgedir(dst_mask_dir)

        img_name = os.path.basename(img_path)
        mask_name = os.path.basename(mask_path)

        dst_img_path = os.path.join(dst_img_dir, img_name)
        dst_mask_path = os.path.join(dst_mask_dir, mask_name)

        if os.path.exists(img_path):
            shutil.copy2(img_path, dst_img_path)
        else:
            print(f"  [!] 源影像不存在: {img_path}")

        if os.path.exists(mask_path):
            shutil.copy2(mask_path, dst_mask_path)
        else:
            print(f"  [!] 源掩码不存在: {mask_path}")

        # ===== 第二遍：原图和 mask 放在同一个子文件夹，保持原命名，并写入报错信息 =====
        case_dir = os.path.join(review_combined_root, phase, f"{case}_{seq}")
        judgedir(case_dir)

        combined_img_path = os.path.join(case_dir, img_name)
        # 如果原图和 mask 文件名相同，放在同一目录会互相覆盖，给 mask 加前缀区分
        if img_name == mask_name:
            combined_mask_name = f"mask_{mask_name}"
        else:
            combined_mask_name = mask_name
        combined_mask_path = os.path.join(case_dir, combined_mask_name)

        if os.path.exists(img_path):
            shutil.copy2(img_path, combined_img_path)
        else:
            print(f"  [!] combined 源影像不存在: {img_path}")
        if os.path.exists(mask_path):
            shutil.copy2(mask_path, combined_mask_path)
        else:
            print(f"  [!] combined 源掩码不存在: {mask_path}")

        error_info_path = os.path.join(case_dir, 'error_info.txt')
        with open(error_info_path, 'w', encoding='utf-8') as ef:
            ef.write(f"错误类型: {err_type}\n")
            ef.write(f"phase: {phase}\n")
            ef.write(f"case: {case}\n")
            ef.write(f"sequence: {seq}\n")
            ef.write(f"影像路径: {img_path}\n")
            ef.write(f"掩码路径: {mask_path}\n")
            ef.write(f"提取失败原因:\n{reason}\n")

        copied += 1

    # 生成说明文档
    summary_path = os.path.join(review_root, 'failed_summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("失败 Case 审查目录说明\n")
        f.write("=" * 70 + "\n\n")

        f.write("[错误类型统计]\n")
        for et, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
            f.write(f"  {et}: {cnt} 例\n")
        f.write(f"  总计: {len(failed_records)} 例\n\n")

        f.write("[各错误类型说明及处理建议]\n\n")

        if 'single_voxel' in type_counts:
            f.write("1. 【单个体素】mask only contains 1 segmented voxel\n")
            f.write("   原因: mask 中 ROI 只有 1 个体素，无法计算任何有意义的影像组学特征\n")
            f.write("   检查重点: 查看原图是否病灶本身就极小，或分割模型漏掉了病灶\n")
            f.write("   处理建议:\n")
            f.write("     a) 若原图确实无可见病灶 -> 该 case 应剔除\n")
            f.write("     b) 若原图有病灶但 mask 只有 1 个体素 -> 重新分割\n")
            f.write("     c) 若病灶本身非常小（<10 个体素）-> 建议剔除，不符合影像组学分析要求\n\n")

        if 'no_label_1' in type_counts:
            f.write("2. 【无标签1】No label object with label 1\n")
            f.write("   原因: mask 中没有值为 1 的标签，或标签 1 的体素极少且不连通\n")
            f.write("   检查重点: 用 ITK-SNAP 或 3D Slicer 打开 mask，查看标签值和连通性\n")
            f.write("   处理建议:\n")
            f.write("     a) 若 mask 非零值是 255 -> 将所有 >0 值重标为 1\n")
            f.write("     b) 若 mask 为空（全 0）-> 重新分割\n")
            f.write("     c) 若 mask 有少量不连通点 -> 取最大连通域 或 膨胀后重采样\n")
            f.write("     d) 若 image 和 mask 空间信息不一致 -> 用 CopyInformation 同步\n\n")

        if 'low_dimensions' in type_counts:
            f.write("3. 【维度不足】mask has too few dimensions\n")
            f.write("   原因: mask 是 1D 或 2D 的，PyRadiomics 要求至少 2D（推荐 3D）\n")
            f.write("   检查重点: 查看 mask 的 shape，可能有某个维度为 1（如单张 slice）\n")
            f.write("   处理建议:\n")
            f.write("     a) 若原数据是 2D -> 在 YAML 中设置 force2D: true\n")
            f.write("     b) 若 3D 数据某个维度为 1 -> 用 SimpleITK 扩展维度，或检查分割流程\n")
            f.write("     c) 若本身只有 1 个 slice -> 这属于数据质量问题，建议剔除\n\n")

        if 'other' in type_counts:
            f.write("4. 【其他错误】\n")
            f.write("   请根据具体报错信息个案分析\n\n")

        f.write("=" * 70 + "\n")
        f.write("[失败文件列表]\n")
        for rec in failed_records:
            f.write(f"  [{rec['err_type']}] {rec['phase']} | {rec['case']} | {rec['sequence']}\n")
            f.write(f"    影像: {rec['img_path']}\n")
            f.write(f"    掩码: {rec['mask_path']}\n")
            f.write(f"    原因: {rec['reason']}\n\n")

    print(f"\n[✓] 共复制 {copied} 组影像到审查目录: {review_root}")
    print(f"[✓] 详细说明已保存: {summary_path}")

    print("\n" + "=" * 70)
    print("[错误类型统计]")
    for et, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {et}: {cnt} 例")
    print("=" * 70)


def judgedir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def run():
    # ====================== 请根据你的环境修改以下路径 ======================
    # 失败记录 CSV 路径（即 extract_radiomics.py 生成的 failed_cases.csv）
    failed_csv_path = r"Z:\data\huyilan2025\tm4.16\tm\2radiomics_features_repaired\failed_cases.csv"

    # 原始影像和掩码根目录
    img_root = r"Z:\data\huyilan2025\tm4.16\tm\1output\images"
    mask_root = r"Z:\data\huyilan2025\tm4.16\tm\1output\masks"

    # 审查目录（有问题的 case 会复制到这里）
    review_root = r"Z:\data\huyilan2025\tm4.16\tm\1failed_cases_for_review2"
    # =====================================================================

    copy_failed_cases(
        failed_csv_path=failed_csv_path,
        img_root=img_root,
        mask_root=mask_root,
        review_root=review_root,
    )


if __name__ == '__main__':
    run()
