# PyRadiomics 参数配置

特征提取参数由项目内的 YAML 文件管理（PyRadiomics 标准参数格式）。通常你不需要手动编辑——直接告诉 Agent 想改什么即可（如「把 binWidth 改成 25」），它会保留 YAML 原有注释和格式进行修改。

## 常用参数

### setting（提取设置）

| 参数 | 说明 | 常用值 |
|------|------|--------|
| `binWidth` | 灰度离散化的 bin 宽度 | 10 / 25（CT 常用 25） |
| `resampledPixelSpacing` | 重采样体素间距 `[x, y, z]`（mm） | `[1, 1, 1]` 或与实测 spacing 一致 |
| `interpolator` | 重采样插值方法 | `sitkBSpline` |
| `normalize` | 是否对图像灰度归一化 | `false`（CT 一般 false） |
| `label` | 掩膜中参与提取的标签值 | `1` |

::: warning spacing 一致性
Agent 在提取前会自动比对图像实测 spacing 与 YAML 的 `resampledPixelSpacing`，不一致时会建议调整。**不要忽略这个提示**——spacing 不一致会直接影响纹理特征的可比性。
:::

### featureClass（特征类别）

```yaml
featureClass:
  firstorder:    # 一阶统计特征
  shape:         # 形状特征（仅原始图像可提取）
  glcm:          # 灰度共生矩阵
  glrlm:         # 灰度游程矩阵
  glszm:         # 灰度区域大小矩阵
  gldm:          # 灰度依赖矩阵
  ngtdm:         # 邻域灰度差矩阵
```

### imageType（图像变换）

```yaml
imageType:
  Original: {}                       # 原始图像
  LoG:                               # 高斯拉普拉斯滤波
    sigma: [1.0, 2.0, 3.0]
  Wavelet: {}                        # 小波变换（8 个分解子带）
```

::: tip 特征数量估算
原始图像约 107 个特征；开启 LoG（3 个 sigma）约 ×3；再开 Wavelet 约 ×8。特征数暴涨时，小样本项目建议减少变换类型，避免维度灾难。
:::

## 让 Agent 帮你调参

| 你说 | Agent 做 |
|------|---------|
| 「把 binWidth 改成 10」 | 修改 YAML（保留注释格式），自动检测缓存失效 |
| 「关掉 Wavelet，特征太多了」 | 注释掉 Wavelet 图像类型 |
| 「当前提取参数是什么」 | 读取 YAML 并解释每项含义 |
| 「spacing 应该设多少」 | 检查图像实测 spacing 并给出建议 |

完整参数定义见 [PyRadiomics 官方文档](https://pyradiomics.readthedocs.io/en/latest/customization.html)。
