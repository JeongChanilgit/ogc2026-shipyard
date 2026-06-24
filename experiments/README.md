# Experiments

탐색 / 검증 / 파일럿 작업 공간. 본격 알고리즘 코드는 `src/` 에, 여기는 실험·노트북·일회성 스크립트.

## 폴더 컨벤션

```
experiments/
├── 2026-MM-DD-주제명/         # 한 실험당 한 폴더
│   ├── notebook.ipynb         # 또는 main.py
│   ├── result.json
│   └── notes.md               # 발견사항 한두 줄
└── scratch/                   # gitignore 됨, 자유 공간
```

## 자주 쓸 실험 후보

- 베이스라인 출력 통계 (방향 선택 분포, 시간 분포, 빈 베이 비율)
- 같은 인스턴스를 timelimit 10/30/60/300 초로 풀었을 때 점수 곡선
- 인스턴스의 (n_blocks × n_bays × avg_K_i × time_horizon) 분포
- bay weight `u_j` 분포 → 큰 베이 / 작은 베이 비대칭성
- preference matrix `S_ij` 분포 → 강한 선호 vs 균등 선호 인스턴스
