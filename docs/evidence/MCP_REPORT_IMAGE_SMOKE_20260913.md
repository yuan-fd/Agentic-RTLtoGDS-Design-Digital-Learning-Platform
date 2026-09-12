# MCP report-image smoke evidence — 2026-09-13

The server-owned OpenROAD-MCP 1.1.0 build was queried through the platform adapter.

- Tool: `list_report_images`
- Inputs: `platform=sky130hd`, `design=ibex`, `run_slug=base`
- Result: 10 report images grouped by ORFS stage.
- Tool: `read_report_image`
- Input image: `final_all.webp`, bounded `max_size_kb=100`
- Result: one inline image block, WebP metadata 512×512, returned successfully.

The adapter accepts only design keys and an image filename, rejects filesystem paths,
and labels the response as MCP exploration data. It does not create a Runtime run or
write Runtime evidence.
