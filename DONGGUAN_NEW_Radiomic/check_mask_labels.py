import os
import SimpleITK as sitk
import numpy as np


def check_mask_labels(mask_root):
    """
    遍历 mask 目录，检查哪些 mask 文件不包含标签值为 1 的体素。

    数据结构：
        masks/
            cj2/
                case_A/
                    T1.nii.gz
                    T2.nii.gz
            jx1/
                ...

    :param mask_root: 掩码根目录
    """
    if not os.path.exists(mask_root):
        print(f"[!] 掩码根目录不存在: {mask_root}")
        return

    no_label_one = []
    empty_mask = []
    total = 0

    for phase in sorted(os.listdir(mask_root)):
        phase_dir = os.path.join(mask_root, phase)
        if not os.path.isdir(phase_dir):
            continue

        for case in sorted(os.listdir(phase_dir)):
            case_dir = os.path.join(phase_dir, case)
            if not os.path.isdir(case_dir):
                continue

            for f in sorted(os.listdir(case_dir)):
                if not f.endswith('.nii.gz'):
                    continue

                mask_path = os.path.join(case_dir, f)
                total += 1

                try:
                    mask = sitk.ReadImage(mask_path)
                    arr = sitk.GetArrayFromImage(mask)
                    unique_vals = np.unique(arr)

                    if len(unique_vals) == 1 and unique_vals[0] == 0:
                        print(f"[空Mask] {phase} | {case} | {f} -> 仅有背景值 0")
                        empty_mask.append(mask_path)
                    elif 1 not in unique_vals:
                        print(f"[无标签1] {phase} | {case} | {f} -> 包含值: {unique_vals}")
                        no_label_one.append((mask_path, unique_vals.tolist()))

                except Exception as e:
                    print(f"[读取失败] {phase} | {case} | {f} -> {e}")

    print("\n" + "=" * 60)
    print(f"扫描完成: 共 {total} 个 mask 文件")
    print(f"  - 空 mask (全为 0): {len(empty_mask)} 个")
    print(f"  - 无标签值为 1 的 mask: {len(no_label_one)} 个")

    if no_label_one:
        print("\n[无标签值为 1 的文件列表]:")
        for path, vals in no_label_one:
            print(f"  {path} -> 包含值: {vals}")

    if empty_mask:
        print("\n[空 mask 文件列表]:")
        for path in empty_mask:
            print(f"  {path}")

    # 可选：保存结果到 txt
    save_path = os.path.join(os.path.dirname(mask_root), "mask_label_check_result.txt")
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(f"扫描目录: {mask_root}\n")
        f.write(f"总文件数: {total}\n")
        f.write(f"空 mask 数: {len(empty_mask)}\n")
        f.write(f"无标签 1 的 mask 数: {len(no_label_one)}\n\n")
        if no_label_one:
            f.write("=== 无标签值为 1 的文件 ===\n")
            for path, vals in no_label_one:
                f.write(f"{path}\t包含值: {vals}\n")
        if empty_mask:
            f.write("\n=== 空 mask 文件 ===\n")
            for path in empty_mask:
                f.write(f"{path}\n")
    print(f"\n[✓] 详细结果已保存: {save_path}")


def run():
    # ====================== 请根据你的环境修改以下路径 ======================
    mask_root = r"Z:\data\huyilan2025\tm4.16\tm\1output\masks"
    # =====================================================================

    check_mask_labels(mask_root)


if __name__ == '__main__':
    run()
