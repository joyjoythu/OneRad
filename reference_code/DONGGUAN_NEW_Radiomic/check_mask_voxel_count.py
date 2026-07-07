import os
import SimpleITK as sitk
import numpy as np


def check_mask_voxels(mask_root, voxel_threshold=10):
    """
    遍历 mask，统计 label 1 的体素数和连通域信息。
    体素数过少（< threshold）的 mask 会被标记出来。

    :param mask_root: 掩码根目录
    :param voxel_threshold: 体素数报警阈值（默认 10）
    """
    if not os.path.exists(mask_root):
        print(f"[!] 掩码根目录不存在: {mask_root}")
        return

    total = 0
    problem_cases = []

    print(f"{'Phase':<10} {'Case':<20} {'Sequence':<20} {'Label_1_Voxels':>15} {'ConnectedComponents':>20} {'Status'}")
    print("-" * 95)

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
                seq_name = f.replace('.nii.gz', '')
                total += 1

                try:
                    mask = sitk.ReadImage(mask_path)
                    arr = sitk.GetArrayFromImage(mask)

                    if 1 not in np.unique(arr):
                        print(f"{phase:<10} {case:<20} {seq_name:<20} {'N/A':>15} {'N/A':>20} {'无标签1'}")
                        problem_cases.append((mask_path, 'no_label_1', 0))
                        continue

                    # label 1 的体素数
                    label_1_voxels = int(np.sum(arr == 1))

                    # 连通域分析（只看 label 1）
                    binary = (arr == 1).astype(np.uint8)
                    binary_img = sitk.GetImageFromArray(binary)
                    cc_filter = sitk.ConnectedComponentImageFilter()
                    cc_img = cc_filter.Execute(binary_img)
                    n_components = cc_filter.GetObjectCount()

                    status = "正常"
                    if label_1_voxels < voxel_threshold:
                        status = f"体素过少(<{voxel_threshold})"
                        problem_cases.append((mask_path, 'too_few_voxels', label_1_voxels))
                    elif n_components > 1:
                        status = f"不连通({n_components}块)"
                        problem_cases.append((mask_path, 'disconnected', label_1_voxels))

                    print(f"{phase:<10} {case:<20} {seq_name:<20} {label_1_voxels:>15} {n_components:>20} {status}")

                except Exception as e:
                    print(f"{phase:<10} {case:<20} {seq_name:<20} {'ERR':>15} {'ERR':>20} {e}")
                    problem_cases.append((mask_path, 'read_error', 0))

    print("\n" + "=" * 95)
    print(f"扫描完成: 共 {total} 个 mask 文件")
    print(f"问题文件: {len(problem_cases)} 个")

    if problem_cases:
        print("\n[问题文件列表]:")
        for path, reason, voxels in problem_cases:
            print(f"  [{reason}] {path} (体素数: {voxels})")

    # 保存结果
    save_path = os.path.join(os.path.dirname(mask_root), "mask_voxel_check_result.txt")
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(f"扫描目录: {mask_root}\n")
        f.write(f"报警阈值: {voxel_threshold} 个体素\n")
        f.write(f"总文件数: {total}\n")
        f.write(f"问题文件数: {len(problem_cases)}\n\n")
        if problem_cases:
            f.write("=== 问题文件列表 ===\n")
            for path, reason, voxels in problem_cases:
                f.write(f"{path}\t原因: {reason}\t体素数: {voxels}\n")
    print(f"\n[✓] 详细结果已保存: {save_path}")


def run():
    # ====================== 请根据你的环境修改以下路径 ======================
    mask_root = r"Z:\data\huyilan2025\tm4.16\tm\1output\masks"

    # 体素数报警阈值：小于此值的 mask 会被标记
    # 建议：
    #   - 形状特征(shape)至少需要几十到上百个体素
    #   - 纹理特征(texture)需要更多（通常建议 >100~1000）
    voxel_threshold = 10
    # =====================================================================

    check_mask_voxels(mask_root, voxel_threshold)


if __name__ == '__main__':
    run()
