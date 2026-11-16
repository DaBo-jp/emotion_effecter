# syntax=docker/dockerfile:1
#
# Cloud Run Jobs のワーカー。`emotion-effecter job prepare|render|finalize` を実行するだけ
# （3段は src/emotion_effecter/job.py）。
#
# 1段目で依存ごと仮想環境を作る（cymatics の C++ の部品を g++ でビルドする）。2段目には
# 仮想環境と ffmpeg・フォントだけ入れる（コンパイラと git を本番のイメージに残さない）。
#
# cymatics は非公開のリポジトリ ∴ GitHub のトークンを BuildKit の secret で渡す。トークンは
# その RUN の環境変数にだけ置き、どの層にも残さない:
#
#     GITHUB_TOKEN=$(gh auth token) docker build --secret id=github_token,env=GITHUB_TOKEN \
#         -t emotion-effecter .
FROM python:3.14-slim-trixie AS build

RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# 依存だけ先に（ソースを変えても、ここの層は作り直さない）
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=github_token,required=true \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/github_token)@github.com/.insteadOf" \
    GIT_CONFIG_VALUE_0="https://github.com/" \
    uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
 && /app/.venv/bin/python -c "import cymatics._native"

FROM python:3.14-slim-trixie

# ffmpeg: 書き出し。fontconfig と Noto CJK: 歌詞（credits）。OS の場所を前提にせず
# fontconfig で探す（roll.py / sing.py）
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/.venv /app/.venv

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    # 包絡のキャッシュはタスクごとの手元（Jobs ではタスク間で共有されない）
    CYMATICS_CACHE_DIR=/tmp/cymatics-cache \
    # C++ の部品が入っていなければ、黙って遅い Python で回さずに断る（CPU 秒で課金される）
    CYMATICS_BACKEND=cpp

WORKDIR /work
ENTRYPOINT ["emotion-effecter"]
CMD ["job", "--help"]
