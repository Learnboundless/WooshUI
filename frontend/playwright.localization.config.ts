import { defineConfig } from "@playwright/test";
import path from "node:path";

const artifacts = path.resolve("../.artifacts/localization-e2e");
export default defineConfig({
  testDir:"./e2e", testMatch:["localization.spec.ts","sfx-batches.spec.ts"], timeout:90000, workers:1,
  use:{channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", baseURL:"http://127.0.0.1:1427", viewport:{width:1440,height:1000}, screenshot:"only-on-failure",trace:"retain-on-failure",
    permissions:["microphone"], launchOptions:{args:["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream"]}},
  webServer:[
    {command:'"../.venv/Scripts/python.exe" ../tests/support/localization_server.py',url:"http://127.0.0.1:8767/api/v1/health",timeout:90000,reuseExistingServer:false, env:{WOOSH_TEST_DIR:artifacts,PYTHONIOENCODING:"utf-8",PYTHONUTF8:"1"}},
    {command:"npm run dev -- --port 1427",url:"http://127.0.0.1:1427",timeout:90000,reuseExistingServer:false,env:{VITE_API_URL:"http://127.0.0.1:8767"}},
  ],
});
