# AutoRadiomics Agent

## 安装

```bash
pip install -r requirements.txt
```

## 运行

### CLI
```bash
python main.py --image-dir ./data/images --clinical ./data/clinical.csv --output-dir ./output
```

### UI
```bash
python main.py --ui
```

### Docker
```bash
docker-compose up --build
```
