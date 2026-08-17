# 自有 R2 更新源放在首位；旧镜像保留为故障回退，避免新源尚未发布时影响现有客户端。
CLOUDFLARE_UPDATE_URLS = (
    'https://pub-f4ec60a8d3514a0b90f5b43a1e4b9913.r2.dev',
    'https://ap-update-cdn-cloudflare.3463343.xyz',
    'https://ap-update-cdn-cloudflare-a3.haiteluo.com',
    'https://ap-update-cdn-cloudflare-a1.3463343.xyz',
    'https://ap-update-cdn-cloudflare.nanoda.work',
    'https://ap-update-cdn-cloudflare-a2.3463343.xyz',
    'https://ap-update-cdn-cloudflare-a1.haiteluo.com',
    'https://ap-update-cdn-cloudflare-a2.haiteluo.com',
    'https://ap-update-cdn-cloudflare-a4.haiteluo.com',
    'https://ap-update-cdn-cloudflare-a3.3463343.xyz',
    'https://ap.update.cdn.cloudflare.3463343.xyz',
)

FALLBACK_UPDATE_URLS = (
    'https://ap.update.cdn.esa.nanoda.work',
)
