# 评估快捷入口。门禁由 evals/runner.py 的退出码决定（硬规则不达标 → 非 0）。
# 用项目 Python 环境运行，例如：conda activate smc_project && make eval-fast

PY ?= python

eval-fast:  # PR 用：跑 smoke 子集（快、便宜）
	$(PY) evals/runner.py --subset smoke

eval-full:  # 全量金标集
	$(PY) evals/runner.py

eval-e2e:  # 经已启动的 API 做 E2E（先 python scripts/start_api.py）
	$(PY) evals/runner.py --base-url http://127.0.0.1:8000

.PHONY: eval-fast eval-full eval-e2e
