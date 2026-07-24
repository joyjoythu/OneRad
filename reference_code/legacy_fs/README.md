# legacy_fs — 旧版目录列举接口（已退役）

来源：OneRad 主应用（`app/api/fs.py` + `frontend/src/api/fs.ts`），2026-07-24 移出。

## 文件

| 文件 | 原位置 | 说明 |
|------|--------|------|
| `fs.py` | `app/api/fs.py` | 旧版后端目录列举接口 `GET /api/fs/list`（列非隐藏子目录 + Windows 盘符） |
| `fs.ts` | `frontend/src/api/fs.ts` | 对应前端 API 客户端 `listDirectory()` |
| `test_api_fs.py` | `tests/test_api_fs.py` | 该接口的 pytest 用例（移出后不可直接运行，仅作参考） |

## 退役原因

- 功能已被 `app/api/filesystem.py`（`/api/filesystem/roots` + `/entries`）+ `frontend/src/api/filesystem.ts` 取代，现役调用方为 `PathPickerDialog.vue`。
- 旧实现无 loopback 限制、无 Docker `ONERAD_FS_ROOTS` 根目录支持；新实现两者皆有。
- 退役时全站无生产代码引用（仅 `ProjectTree.spec.ts` 中一处失效 mock，已同步清理）。
