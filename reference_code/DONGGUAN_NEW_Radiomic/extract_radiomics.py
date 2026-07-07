import os
import re
import csv
import h5py
import numpy as np
from Atsea_def import cir_get_features, judgedir


def extract_radiomics_for_dataset(
    img_root,
    mask_root,
    save_root,
    yaml_map,
    aggregate_csv=True,
    csv_path=None
):
    """
    针对当前数据结构的影像组学特征提取。

    数据结构：
        images/
            cj2/
                case_A/
                    T1.nii.gz
                    T2.nii.gz
                    T1+C.nii.gz
                case_B/
                    ...
            jx1/
                ...
            wu3/
                ...
        masks/
            cj2/
                case_A/
                    T1.nii.gz
                    T2.nii.gz
                    T1+C.nii.gz
                ...

    :param img_root: 影像根目录（如 ./images）
    :param mask_root: 掩码根目录（如 ./masks）
    :param save_root: 特征保存根目录
    :param yaml_map: 字典，映射 {phase_name: yaml配置文件路径}
    :param aggregate_csv: 是否汇总所有特征到一个 CSV
    :param csv_path: CSV 保存路径（默认 save_root/all_features.csv）
    """
    sep = os.sep

    # 创建保存根目录
    judgedir(save_root, RemoveFlag=False)

    # 汇总数据容器
    all_records = []
    feature_names = None

    # 失败记录容器
    failed_records = []

    # 遍历每个类别/期相（cj2, jx1, wu3）
    for phase in sorted(yaml_map.keys()):
        yaml_path = yaml_map[phase]
        if not os.path.exists(yaml_path):
            print(f"[!] 跳过 [{phase}]：配置文件不存在 {yaml_path}")
            continue

        img_phase_dir = os.path.join(img_root, phase)
        mask_phase_dir = os.path.join(mask_root, phase)

        if not os.path.exists(img_phase_dir):
            print(f"[!] 跳过 [{phase}]：影像目录不存在 {img_phase_dir}")
            continue
        if not os.path.exists(mask_phase_dir):
            print(f"[!] 跳过 [{phase}]：掩码目录不存在 {mask_phase_dir}")
            continue

        # 当前类别的特征保存目录
        phase_save_dir = os.path.join(save_root, phase)
        judgedir(phase_save_dir, RemoveFlag=False)

        # 获取病例列表（只取文件夹）
        case_list = sorted([
            d for d in os.listdir(img_phase_dir)
            if os.path.isdir(os.path.join(img_phase_dir, d))
        ])

        print(f"\n{'='*60}")
        print(f"[Phase] {phase} | 病例数: {len(case_list)} | YAML: {yaml_path}")
        print(f"{'='*60}")

        for case_idx, case in enumerate(case_list, 1):
            img_case_dir = os.path.join(img_phase_dir, case)
            mask_case_dir = os.path.join(mask_phase_dir, case)

            if not os.path.exists(mask_case_dir):
                print(f"  [{case_idx}/{len(case_list)}] {case} -> 掩码病例目录缺失，跳过")
                continue

            # 获取该病例下的所有 nii.gz 影像文件
            img_files = sorted([f for f in os.listdir(img_case_dir) if f.endswith('.nii.gz')])

            if not img_files:
                print(f"  [{case_idx}/{len(case_list)}] {case} -> 无影像文件，跳过")
                continue

            for seq_file in img_files:
                img_path = os.path.join(img_case_dir, seq_file)
                mask_path = os.path.join(mask_case_dir, seq_file)

                # 检查对应掩码是否存在
                if not os.path.exists(mask_path):
                    print(f"  [{case_idx}/{len(case_list)}] {case} | {seq_file} -> 掩码缺失，跳过")
                    continue

                # 输出文件名（去除 .nii.gz）
                seq_name = seq_file.replace('.nii.gz', '')
                h5_name = f"{case}_{seq_name}.h5"
                h5_path = os.path.join(phase_save_dir, h5_name)

                # 断点续传：已存在则跳过
                if os.path.exists(h5_path):
                    print(f"  [{case_idx}/{len(case_list)}] {case} | {seq_file} -> 已处理，跳过")
                    # 若汇总 CSV，仍尝试读取已有 h5（可选）
                    continue

                print(f"  [{case_idx}/{len(case_list)}] {case} | {seq_file} -> 提取中...")

                try:
                    # 提取特征
                    feature_dict = cir_get_features(img_path, mask_path, yaml_path)
                except Exception as e:
                    err_msg = str(e)
                    print(f"  [X] {case} | {seq_file} 提取失败: {err_msg}")
                    failed_records.append({
                        'phase': phase,
                        'case': case,
                        'sequence': seq_name,
                        'img_path': img_path,
                        'mask_path': mask_path,
                        'reason': err_msg,
                    })
                    continue

                # 保存为 h5
                feature_values = np.array(list(feature_dict.values())).reshape(1, -1)
                with h5py.File(h5_path, 'w') as f:
                    f.create_dataset('f_values', data=feature_values)

                # 收集汇总信息
                if aggregate_csv:
                    if feature_names is None:
                        feature_names = list(feature_dict.keys())
                    record = {
                        'phase': phase,
                        'case': case,
                        'sequence': seq_name,
                        'img_path': img_path,
                        'mask_path': mask_path,
                    }
                    for k, v in feature_dict.items():
                        record[k] = v
                    all_records.append(record)

    # 汇总输出 CSV
    if aggregate_csv and all_records:
        if csv_path is None:
            csv_path = os.path.join(save_root, 'all_features.csv')

        fieldnames = ['phase', 'case', 'sequence', 'img_path', 'mask_path'] + feature_names
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as cf:
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_records)
        print(f"\n[✓] 特征汇总 CSV 已保存: {csv_path} (共 {len(all_records)} 条记录)")

    # 输出失败记录
    if failed_records:
        failed_csv_path = os.path.join(save_root, 'failed_cases.csv')
        failed_fieldnames = ['phase', 'case', 'sequence', 'img_path', 'mask_path', 'reason']
        with open(failed_csv_path, 'w', newline='', encoding='utf-8-sig') as cf:
            writer = csv.DictWriter(cf, fieldnames=failed_fieldnames)
            writer.writeheader()
            writer.writerows(failed_records)

        print(f"\n[!] 提取失败汇总: 共 {len(failed_records)} 例")
        for rec in failed_records:
            print(f"    - [{rec['phase']}] {rec['case']} | {rec['sequence']}: {rec['reason']}")
        print(f"[✓] 失败记录已保存: {failed_csv_path}")
    else:
        print("\n[✓] 所有影像均提取成功，无失败记录。")

    print("\n[Done] 全部处理完成。")


def run():
    # ====================== 请根据你的环境修改以下路径 ======================

    # 数据根目录（当前脚本所在目录下的 images 和 masks）
    img_root = r"Z:\data\huyilan2025\tm4.16\tm\1output\images"
    mask_root = r"Z:\data\huyilan2025\tm4.16\tm\1output\masks"

    # 特征保存目录
    save_root = r"Z:\data\huyilan2025\tm4.16\tm\2radiomics_features"

    # 每个 phase 对应的 yaml 配置文件（若某些 phase 配置相同，可指向同一文件）
    yaml_map = {
        'cj2': r"D:\python_Project\HY_Dongguan_Prj\DONGGUAN_NEW_Radiomic\Params_labels_qian.yaml",
        'jx1': r"D:\python_Project\HY_Dongguan_Prj\DONGGUAN_NEW_Radiomic\Params_labels_qian.yaml",
        'wu3': r"D:\python_Project\HY_Dongguan_Prj\DONGGUAN_NEW_Radiomic\Params_labels_qian.yaml",
    }

    # 是否汇总 CSV，以及 CSV 保存路径（None 则默认存到 save_root/all_features.csv）
    aggregate_csv = True
    csv_path = None  # 或自定义，如 r"...\features.csv"

    # =====================================================================

    extract_radiomics_for_dataset(
        img_root=img_root,
        mask_root=mask_root,
        save_root=save_root,
        yaml_map=yaml_map,
        aggregate_csv=aggregate_csv,
        csv_path=csv_path,
    )


if __name__ == '__main__':
    run()
