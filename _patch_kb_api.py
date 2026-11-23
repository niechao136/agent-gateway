import io
p = r"D:\agent\agent-gateway\web\src\lib\api.ts"
s = io.open(p, encoding="utf-8").read()
old = '''export function listRagflowDatasets(body: {
  base_url: string;
  api_key: string;
}): Promise<{ datasets: DatasetItem[] }> {
  return request("/knowledge/datasets", { method: "POST", body: JSON.stringify(body) });
}'''
new = '''export async function listRagflowDatasets(body: {
  base_url: string;
  api_key: string;
}): Promise<{ datasets: DatasetItem[] }> {
  const q = new URLSearchParams({ base_url: body.base_url, api_key: body.api_key });
  const rows = await request<{ id: string; name: string }[]>(`/knowledge/list-datasets?${q.toString()}`);
  return { datasets: rows };
}'''
assert old in s, "not found"
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("PATCHED api.ts")
