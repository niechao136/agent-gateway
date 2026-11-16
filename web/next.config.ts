import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // ⚠️ 注意：rewrites 在 `next build` 时求值并写死进产物，
  // 运行时再改 CONTROL_URL 环境变量**不会生效**。
  // 因此这里在构建期读取，Dockerfile 通过 build-arg 传入。
  // 生产环境由 nginx 直接反代 /api/*，这条 rewrite 主要服务本地开发。
  async rewrites() {
    const target = process.env.CONTROL_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
};

export default nextConfig;
