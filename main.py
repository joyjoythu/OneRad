import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--image-dir", required=True)
    parser.add_argument("--clinical", required=True)
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="", help="逗号分隔的协变量列名")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-chat")
    args = parser.parse_args()

    # Task 18 将在此处实例化 Orchestrator 并运行


if __name__ == "__main__":
    main()
