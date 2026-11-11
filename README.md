# tiktok-comments-export: TikTok comments to CSV or JSON

Export the comments of one or many TikTok videos to a CSV file (or JSON Lines): comment text, likes, reply count,
author handle and time. **No TikTok login, no browser automation, no cookies.** One Python file, standard library
only, Python 3.9+.

Good for: reading what buyers say under product videos, sentiment and theme analysis, feeding comments to an AI,
or keeping a record of a campaign's comments.

## Use it

Get a key at [okdata](https://okdata.online/signup/?src=gh-tiktok-comments-export), then:

```bash
git clone https://github.com/okdataapi/tiktok-comments-export
cd tiktok-comments-export
export OKDATA_API_KEY=okd_...     # keep it out of code and commits

# one video, about 100 comments, to a CSV file
python3 export_comments.py https://www.tiktok.com/@user/video/7305085486984858894 --pages 2 -o comments.csv

# many videos from a file (one link or id per line), JSON Lines
python3 export_comments.py --file videos.txt --pages 4 --format jsonl -o comments.jsonl

# see what it would cost first
python3 export_comments.py --file videos.txt --pages 4 --dry-run
```

Links can be full video links, short `vm.tiktok.com` / `vt.tiktok.com` links, or bare video ids.

| Column | |
|---|---|
| `video_id`, `comment_id`, `parent_id` | ids; `parent_id` is empty for top-level comments |
| `text` | the comment |
| `likes`, `replies` | counts at fetch time |
| `published_at` | ISO 8601, UTC |
| `author_username`, `author_name` | the commenter's handle and display name |

## What it costs

| Step | Endpoint | Price |
|---|---|---|
| One page of about 50 comments | [`tiktok.videos.comments.list`](https://okdata.online/apis/tiktok/videos/comments/list/) | $0.002 |
| Resolving a short link (only for vm/vt links) | [`tiktok.videos.get`](https://okdata.online/apis/tiktok/videos/get/) | $0.002 |

1,000 comments cost about $0.04. Failed calls are free. The script prints the most a run can cost before it starts
and refuses runs over `--budget` (default $1). Prices: [prices.json](https://github.com/okdataapi/okdata/blob/main/docs/prices.json).

## Notes

- A sample project by [okdata](https://okdata.online), not affiliated with TikTok or ByteDance. The script only
  calls the okdata API; there is no scraper in it.
- Public comments only. Respect people's privacy: analyse what is said, do not build profiles of commenters.
- Working in an AI agent? Connect okdata's remote MCP server `https://api.okdata.online/mcp`, or install the
  `okdata-comments` skill from [okdataapi/skills](https://github.com/okdataapi/skills).
- Tests: `python3 -m unittest discover -s tests` (a local mock server; no network, no cost).
- Issues and ideas welcome. MIT licence.

---

## 中文

把一个或多个 TikTok 视频的评论导出成 CSV（或 JSON Lines）：评论内容、点赞、回复数、作者和时间。不用登录 TikTok，
不用浏览器自动化，不用 Cookie。一个 Python 文件，只用标准库。每页约 50 条评论 $0.002，失败不扣钱，1,000 条约 $0.04。
先在 [okdata](https://okdata.online/zh/signup/?src=gh-tiktok-comments-export) 注册拿 key，放进 `OKDATA_API_KEY`，然后
`python3 export_comments.py <视频链接> --pages 2 -o comments.csv`。MIT 许可证。
