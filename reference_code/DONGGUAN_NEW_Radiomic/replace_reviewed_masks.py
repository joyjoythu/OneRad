import os
import shutil


def replace_reviewed_masks(
    mask_root,
    failed_case_root,
    backup_root,
    auto_confirm=False,
):
    """
    遍历 failed_case_root 中重新绘制的 mask，
    先预览，经用户确认后再替换回 mask_root，并备份旧 mask。
    """

    if not os.path.exists(failed_case_root):
        print(f"[!] 审查目录不存在: {failed_case_root}")
        return

    # ===================== 第一阶段：扫描并生成替换计划 =====================
    plans = []
    skipped_cases = []

    for phase in sorted(os.listdir(failed_case_root)):
        phase_path = os.path.join(failed_case_root, phase)
        if not os.path.isdir(phase_path):
            continue

        for case_folder in sorted(os.listdir(phase_path)):
            case_dir = os.path.join(phase_path, case_folder)
            if not os.path.isdir(case_dir):
                continue

            case_key = f"{phase}/{case_folder}"
            error_info_path = os.path.join(case_dir, 'error_info.txt')

            if not os.path.exists(error_info_path):
                skipped_cases.append((case_key, "无 error_info.txt"))
                continue

            info = parse_error_info(error_info_path)
            orig_mask_path = info.get('orig_mask_path')
            orig_img_path = info.get('orig_img_path')

            if not orig_mask_path:
                skipped_cases.append((case_key, "error_info.txt 中未解析到原始 mask 路径"))
                continue

            orig_mask_name = os.path.basename(orig_mask_path)
            orig_img_name = os.path.basename(orig_img_path) if orig_img_path else ""
            new_mask_name = find_new_mask(case_dir, orig_mask_name, orig_img_name)

            if not new_mask_name:
                skipped_cases.append((case_key, f"在审查目录中未找到新 mask（原始应为: {orig_mask_name}）"))
                continue

            new_mask_path = os.path.join(case_dir, new_mask_name)
            rel_backup = os.path.relpath(orig_mask_path, mask_root)
            backup_path = os.path.join(backup_root, rel_backup)

            plans.append({
                'case_key': case_key,
                'case_dir': case_dir,
                'new_mask_name': new_mask_name,
                'new_mask_path': new_mask_path,
                'orig_mask_path': orig_mask_path,
                'orig_mask_name': orig_mask_name,
                'backup_path': backup_path,
            })

    # ===================== 第二阶段：显示预览 =====================
    print("\n" + "=" * 70)
    print("Mask 替换预览")
    print("=" * 70)

    if not plans:
        print("\n[!] 未找到任何可替换的 mask。\n")
        if skipped_cases:
            print("[跳过原因]")
            for case_key, reason in skipped_cases:
                print(f"  - {case_key}: {reason}")
        return

    print(f"\n共扫描到 {len(plans)} 个可替换的 case：\n")
    for i, plan in enumerate(plans, 1):
        print(f"  [{i}] {plan['case_key']}")
        print(f"      新 mask : {plan['new_mask_name']}")
        print(f"      目标位置: {plan['orig_mask_path']}")
        print(f"      备份位置: {plan['backup_path']}")
        print()

    if skipped_cases:
        print(f"另有 {len(skipped_cases)} 个 case 被跳过：")
        for case_key, reason in skipped_cases:
            print(f"  - {case_key}: {reason}")
        print()

    # ===================== 第三阶段：用户确认 =====================
    if not auto_confirm:
        confirm = input("确认执行上述替换？(y/n): ").strip().lower()
        if confirm not in ('y', 'yes'):
            print("\n[已取消] 未执行任何替换。\n")
            return

    # ===================== 第四阶段：执行替换 =====================
    print("\n" + "=" * 70)
    print("开始执行替换...")
    print("=" * 70 + "\n")

    judgedir(backup_root)
    replaced = 0
    errors = 0
    log_lines = []

    for plan in plans:
        case_key = plan['case_key']
        new_mask_path = plan['new_mask_path']
        orig_mask_path = plan['orig_mask_path']
        backup_path = plan['backup_path']
        new_mask_name = plan['new_mask_name']
        orig_mask_name = plan['orig_mask_name']

        print(f"[{replaced + errors + 1}/{len(plans)}] 正在替换: {case_key}")

        try:
            # 如果新 mask 和原 mask 是同一个物理文件（硬链接），直接跳过
            if os.path.exists(new_mask_path) and os.path.exists(orig_mask_path):
                if os.path.samefile(new_mask_path, orig_mask_path):
                    msg = f"[→] {case_key}: 新 mask 与原 mask 为同一文件（硬链接），无需替换"
                    print(f"       ↳ {msg}\n")
                    log_lines.append(msg)
                    replaced += 1
                    continue

            judgedir(os.path.dirname(backup_path))
            if os.path.exists(orig_mask_path):
                shutil.copy2(orig_mask_path, backup_path)
                print(f"       ↳ 已备份原 mask -> {backup_path}")
            else:
                print(f"       ↳ 原 mask 不存在，直接写入新 mask")

            judgedir(os.path.dirname(orig_mask_path))
            shutil.copy2(new_mask_path, orig_mask_path)

            msg = f"[✓] {case_key}: 替换成功 ({new_mask_name} -> {orig_mask_name})"
            print(f"       ↳ {msg}\n")
            log_lines.append(msg)
            replaced += 1
        except Exception as e:
            err_msg = f"[✗] {case_key}: 替换失败: {e}"
            print(f"       ↳ {err_msg}\n")
            log_lines.append(err_msg)
            errors += 1

    # 写日志
    log_path = os.path.join(backup_root, 'replace_log.txt')
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("Mask 替换记录\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"审查目录: {failed_case_root}\n")
        f.write(f"原始 mask 根目录: {mask_root}\n")
        f.write(f"备份目录: {backup_root}\n\n")
        f.write(f"成功替换: {replaced}\n")
        f.write(f"跳过: {len(skipped_cases)}\n")
        f.write(f"失败: {errors}\n\n")
        for line in log_lines:
            f.write(line + "\n")

    print("=" * 70)
    print(f"[完成] 成功替换: {replaced} | 跳过: {len(skipped_cases)} | 失败: {errors}")
    print(f"[日志] {log_path}")
    print("=" * 70)


def parse_error_info(error_info_path):
    """从 error_info.txt 中解析原始路径"""
    info = {}
    with open(error_info_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('掩码路径:'):
                info['orig_mask_path'] = line.split(':', 1)[1].strip()
            elif line.startswith('影像路径:'):
                info['orig_img_path'] = line.split(':', 1)[1].strip()
    return info


def find_new_mask(case_dir, orig_mask_name, orig_img_name):
    """
    在审查目录中查找新绘制的 mask 文件。
    匹配规则（按优先级）：
      1) mask_{orig_mask_name}
      2) 与 orig_mask_name 同名的文件（用户覆盖保存）
      3) 排除原图和 error_info.txt 后唯一的 .nii.gz/.nii
      4) 文件名包含 mask 字样且唯一
    """
    candidates = []
    for fname in os.listdir(case_dir):
        fpath = os.path.join(case_dir, fname)
        if not os.path.isfile(fpath):
            continue
        lower = fname.lower()
        if lower == 'error_info.txt':
            continue
        if lower.endswith('.nii.gz') or lower.endswith('.nii'):
            candidates.append(fname)

    if not candidates:
        return None

    # 1) 优先匹配 mask_前缀
    prefixed = f"mask_{orig_mask_name}"
    for c in candidates:
        if c == prefixed:
            return c

    # 2) 完全同名
    for c in candidates:
        if c == orig_mask_name:
            return c

    # 3) 排除原图后只剩一个
    non_img = [c for c in candidates if c != orig_img_name]
    if len(non_img) == 1:
        return non_img[0]

    # 4) 包含 mask 字样且唯一
    mask_named = [c for c in candidates if 'mask' in c.lower() and c != orig_img_name]
    if len(mask_named) == 1:
        return mask_named[0]

    return None


def judgedir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def run():
    # ====================== 请根据你的环境修改以下路径 ======================
    # 原始 mask 根目录（和 copy_failed_cases.py 保持一致）
    mask_root = r"Z:\data\huyilan2025\tm4.16\tm\1output\masks"

    # 重新绘制后的 mask 所在目录（直接指向包含各 case 子文件夹的根目录）
    failed_case_root = r"Z:\data\huyilan2025\tm4.16\tm\new case3\new case3"

    # 旧 mask 备份根目录
    backup_root = r"Z:\data\huyilan2025\tm4.16\tm\new case3\backup_original_masks"

    # 是否自动确认（不询问直接执行）。建议首次运行时保持 False，确认无误后可设为 True
    auto_confirm = False
    # =====================================================================

    replace_reviewed_masks(
        mask_root=mask_root,
        failed_case_root=failed_case_root,
        backup_root=backup_root,
        auto_confirm=auto_confirm,
    )


if __name__ == '__main__':
    run()
