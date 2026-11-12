---
name: chrome-extension-mv3
description: Build Manifest V3 Chrome extensions and publish to the Web Store - lifecycle limits, permissions, APIs, security, policy traps. Use when creating or reviewing a Chrome extension.
allowed-tools: Read, Write, Edit, Bash
version: 1.0
---

# Chrome extension (MV3)

Source: developer.chrome.com/docs/extensions and /docs/webstore, crawled 2026-10-05
(250 pages). The cheat-sheets below were drafted by free fleet models (NouGenOpen) and
spot-checked against the pages; treat anything not marked VERIFIED as a draft and
confirm against the page before relying on it.

## VERIFIED rules (read from the docs)
- Service worker is terminated after 30s idle, after a single request over 5 min, or a
  fetch response over 30s. Extension API calls reset the idle timer.
- Register listeners at the TOP LEVEL of the service worker. Keep no state in globals;
  use `chrome.storage` / IndexedDB.
- Service workers and extension pages make cross-origin `fetch` with `host_permissions`;
  content scripts stay under the page's same-origin policy. Route network calls through
  the worker; never let a content script pick the URL.
- `contextMenus` needs the permission; create menus in `runtime.onInstalled`, handle
  `contextMenus.onClicked` (`selectionText`, `pageUrl`).
- From Chrome 148 all APIs are also under `browser.*`; for new extensions set
  `minimum_chrome_version` and use `browser` unconditionally.
- `commands` and `action` are manifest KEYS, not permissions (a draft digest called
  them permissions; that is wrong).
- A tool that returns HTTP 200 may not have done the work: read the response's own
  success field (the NouGen `/capture` returns `captured`).

## Worked example
`integrations/chrome-capture/` in NouGenShards: MV3 capture-to-shards extension
(context menu + `Alt+Shift+S`, options page, per-origin host permission requested at
save time, token only in `chrome.storage.local`, UI from NouGenDesign `nougen-core`
tokens, pure helpers unit-tested under `node --test`).

## Draft cheat-sheets (NouGenOpen, unverified detail)

### architecture
- **activeTab Permission:**
  - Grants temporary access to the currently active tab when the user invokes the extension (e.g., by clicking the action).
  - Access lasts while the user is on the page and is revoked when the user navigates away or closes the tab.
  - Does not grant access to restricted pages (e.g., `chrome://` pages).
  - Example: `permissions: ["activeTab", "scripting"]`.

- **Browser Namespace:**
  - Available from Chrome 148.
  - Use `browser` namespace in addition to `chrome` namespace.
  - Both namespaces point to the same API objects.
  - For new extensions, set `minimum_chrome_version` to "148" and use `browser` unconditionally.
  - For existing extensions, check user Chrome versions and use runtime guards if necessary.

- **Content Filtering:**
  - Use `browser.declarativeNetRequest` API to filter network requests.
  - Static rules: Up to 300,000 shared globally, 30,000 per extension.
  - Dynamic rules: Added at runtime.
  - Example: Block, redirect, or modify headers of network requests.

- **Content Scripts:**
  - Run in the context of web pages and can read and modify page content.
  - Access to limited extension APIs: `dom`, `i18n`, `storage`, `runtime.connect()`, `runtime.getManifest()`, `runtime.getURL()`, `runtime.id`, `runtime.onConnect`, `runtime.onMessage`, `runtime.sendMessage()`.
  - Live in isolated worlds, not accessible to the page or other extensions.
  - Example: Injected into web pages to modify DOM.

- **Cross-Origin Isolation:**
  - Opt into cross-origin isolation using `cross_origin_embedder_policy` and `cross_origin_opener_policy` in the manifest.
  - Example: `cross_origin_embedder_policy: { "value": "require-corp" }, cross_origin_opener_policy: { "value": "same-origin" }`.
  - Not fully implemented for service and shared workers.

- **Declare Permissions:**
  - Use `permissions`, `optional_permissions`, `content_scripts.matches`, `host_permissions`, `optional_host_permissions` in the manifest.
  - Example: `permissions: ["activeTab", "contextMenus", "storage"]`.
  - `host_permissions` allow access to specific hosts.
  - Example: `host_permissions: ["https://www.developer.chrome.com/*"]`.

- **Match Patterns:**
  - Format: `<scheme>://<host>:<port>/<path>`.
  - Schemes: `http`, `https`, `*` (matches `http` or `https`), `file`.
  - Host: `*` for wildcard subdomains, `*` for all hosts.
  - Example: `https://*/*` matches all HTTPS URLs.
  - Special cases: `<all_urls>` matches any URL, `file:///*` matches local files.

- **Message Passing:**
  - Use `runtime.sendMessage()` and `tabs.sendMessage()` for one-time requests.
  - Use `runtime.onMessage` to listen for messages.
  - Example: `const response = await browser.runtime.sendMessage({ greeting: "hello" });`.

- **Native Messaging:**
  - Register a native messaging host using a JSON manifest.
  - Example: `path: "C:\\Program Files\\My Application\\chrome_native_messaging_host.exe"`.
  - Communicate using standard input and output streams.

- **Cross-Origin Network Requests:**
  - Extension origins can make cross-origin requests with host permissions.
  - Example: `host_permissions: ["https://www.google.com/"]`.
  - Content scripts are subject to the same origin policy unless the extension has host permissions.

- **Permission Warnings:**
  - Some permissions trigger warnings during installation.
  - Example: `tabs` permission triggers a warning.
  - Use optional permissions to request at runtime.
  - Best practices: Request relevant permissions, use optional permissions, use `activeTab` for temporary access.
### howto_security
- **DevTools Extensions**
  - **DevTools Page**: Add `devtools_page` in manifest: `"devtools_page": "devtools.html"`.
  - **APIs**: `devtools.inspectedWindow`, `devtools.network`, `devtools.panels`, `devtools.recorder`, `devtools.performance`.
  - **Access**: DevTools page can access these APIs and communicate with the service worker.
  - **Restrictions**: Content scripts and other extension pages don't have access to DevTools APIs.
  - **Browser Namespace**: Available in Chrome 152+.

- **Distribution**
  - **Chrome Web Store**: Officially supported, requires registration.
  - **Self-Hosting**: Only for managed environments with enterprise policies.
  - **Linux**: Users can install self-hosted extensions manually.
  - **Windows/MacOS**: Self-hosted extensions require enterprise policies.
  - **Preferences/Registry**: JSON file (Linux/macOS) or Windows registry for automatic installation.
  - **Update URL**: Must point to the Chrome Web Store for Windows/MacOS.

- **Self-Hosting for Linux**
  - **CRX Files**: Download from Chrome Web Store or create locally.
  - **Create CRX**: Use `chrome://extensions/` in Developer Mode, specify extension directory.
  - **Update**: Increase version number in `manifest.json`.

- **Googlebook OS**
  - **Platform Detection**: `chrome.runtime.getPlatformInfo().os` returns 'android', `navigator.userAgent` contains 'CrOS'.
  - **Unsupported APIs**: ChromeOS-only APIs are undefined.
  - **Native Messaging**: Not available yet.
  - **Keyboard Shortcuts**: Use Linux keybindings.

- **Firebase Cloud Messaging (FCM)**
  - **Prerequisites**: Firebase account, enable Cloud Messaging API.
  - **Manifest**: Add `"permissions": ["gcm"]`.
  - **Register**: Use `browser.gcm.register` with Sender ID.
  - **Listen for Messages**: Add event listeners for incoming messages.

- **Google Analytics**
  - **Measurement Protocol**: Required for Manifest V3.
  - **API Credentials**: Generate Measurement ID and API secret.
  - **Web Data Stream**: Set up in Google Analytics Admin.
  - **Send Events**: Use HTTP requests to send events directly.

- **OAuth 2.0**
  - **Manifest**: Add `"permissions": ["identity"]`.
  - **Service Worker**: Handle user actions and API calls.
  - **Consistent ID**: Upload extension to Developer Dashboard to preserve ID.
  - **User Prompt**: Permission prompt not shown for extensions; use notifications permission.

- **Web Push**
  - **Permissions**: Add `"permissions": ["notifications"]`.
  - **Push Service**: Firebase Cloud Messaging for Chrome.
  - **Provider**: Choose a Push provider and configure backend.
  - **User Permission**: Required for Push API.

- **Sandboxing eval()**
  - **CSP**: Default Content Security Policy restricts inline scripts and eval.
  - **Sandbox**: List HTML files as sandboxed in manifest.
  - **Security**: Sandboxed pages have unique origin and no access to browser APIs.
  - **Messaging**: Use iframes and postMessage for communication.
### apis_for_capture
- **Storage API**
  - **Permissions**: `"storage"`
  - **Usage**: `browser.storage.local.set/get`, `browser.storage.sync.set/get`, `browser.storage.session.set/get`
  - **Storage Areas**: `local`, `sync`, `session`
  - **Persistence**: Data persists even if user clears cache and browsing history
  - **Managed Storage**: Exclusive read-only area for enterprise policies

- **Scripting API**
  - **Permissions**: `"scripting"`, `"activeTab"` or `"host_permissions"`
  - **Usage**: `browser.scripting.executeScript`
  - **Injection Targets**: `tabId`, `allFrames`, `frameIds`
  - **Note**: Cannot specify both `frameIds` and `allFrames`

- **Context Menus API**
  - **Permissions**: `"contextMenus"`
  - **Usage**: `browser.contextMenus.create`, `browser.contextMenus.update`
  - **Context Types**: `"all"`, `"page"`, `"frame"`, `"selection"`, `"link"`, `"editable"`, `"image"`, `"video"`, `"audio"`, `"launcher"`, `"action"`, `"tab"`
  - **Icons**: 16x16 pixels required, 48x48 and 128x128 recommended
  - **Document URL Patterns**: `documentUrlPatterns` to control visibility

- **Action API**
  - **Permissions**: `"action"`
  - **Usage**: `browser.action.setDefaultIcon`, `browser.action.setTitle`, `browser.action.setPopup`
  - **Icon Sizes**: 16, 24, 32 DIPs
  - **Note**: Every extension has an icon in the toolbar, even without the `action` key

- **Commands API**
  - **Permissions**: `"commands"`
  - **Usage**: `browser.commands.onCommand.addListener`
  - **Suggested Keys**: `"A"-"Z"`, `"0"-"9"`, `","`, `"."`, `"Home"`, `"End"`, `"PageUp"`, `"PageDown"`, `"Space"`
  - **Platform-Specific Shortcuts**: `default`, `chromeos`, `linux`, `mac`, `windows`
  - **Limit**: At most 4 suggested keyboard shortcuts

- **Notifications API**
  - **Permissions**: `"notifications"`
  - **Usage**: `browser.notifications.create`
  - **Types**: `basic`, `image`, `list`, `progress`
  - **Properties**: `iconUrl`, `title`, `message`, `buttons`, `contextMessage`, `priority`, `eventTime`
  - **Note**: `iconUrl` and `message` are required

- **Permissions API**
  - **Usage**: `browser.permissions.request`, `browser.permissions.remove`
  - **Optional vs Required**: Required for core functionality, optional for additional features
  - **Advantages**: Fewer prompts, better security, better user information

- **Side Panel API**
  - **Permissions**: `"sidePanel"`
  - **Usage**: `browser.sidePanel.setOptions`
  - **Features**: Persistent UI, available on specific websites, access to all Chrome APIs
  - **Manifest**: `default_path` to set initial side panel content

- **Tabs API**
  - **Permissions**: `"tabs"`, `"activeTab"`, `"host_permissions"`
  - **Usage**: `browser.tabs.create`, `browser.tabs.update`, `browser.tabs.query`
  - **Sensitive Properties**: `url`, `pendingUrl`, `title`, `favIconUrl`
  - **Host Permissions**: Interact with tabs using `captureVisibleTab`, `executeScript`, `insertCSS`, `removeCSS`

- **Runtime API**
  - **Permissions**: `"nativeMessaging"`
  - **Usage**: `browser.runtime.connect`, `browser.runtime.onConnect`, `browser.runtime.sendMessage`
  - **Metadata**: `browser.runtime.getManifest`, `browser.runtime.getPlatformInfo`
  - **Lifecycle**: `browser.runtime.onInstalled`, `browser.runtime.onStartup`, `browser.runtime.openOptionsPage`
  - **Utilities**: `browser.runtime.getURL`

- **Alarms API**
  - **Permissions**: `"alarms"`
  - **Usage**: `browser.alarms.create`, `browser.alarms.get`, `browser.alarms.clear`
  - **Device Sleep**: Alarms continue to run but do not wake up the device
  - **Persistence**: `persistAcrossSessions` (true/false)
  - **Note**: Check and recreate important alarms on service worker startup
### webstore
- **Account Deletion:**
  - **Permanent Action:** Cannot be undone.
  - **Unpublish Items:** Must unpublish all items before deletion.
  - **Admin Requirement:** Only Admins can delete publishers.
  - **Last Admin:** Cannot delete the last Admin of a publisher; must share ownership first.
  - **Dashboard Actions:** Unpublish via "more options" > "Unpublish".
  - **Re-publish:** Requires new version and review.

- **API Reference:**
  - **Service Accounts:** Supported for V2.
  - **Client Verification:** Unverified apps can still use the API for personal use.
  - **Discovery Document:** `https://chromewebstore.googleapis.com/$discovery/rest?version=v2`.
  - **Service Endpoint:** `https://chromewebstore.googleapis.com`.

- **REST Resources:**
  - **Media:**
    - **Upload:** `POST /upload/v2/{name=publishers/*/items/*}:upload`.
    - **No Persistent Data.**
    - **Response Fields:** `name`, `itemId`, `crxVersion`, `uploadState`.
    - **OAuth Scope:** `https://www.googleapis.com/auth/chromewebstore`.
  - **Publishers.Items:**
    - **Cancel Submission:** `POST /v2/{name=publishers/*/items/*}:cancelSubmission`.
    - **Fetch Status:** `GET /v2/{name=publishers/*/items/*}:fetchStatus`.
    - **Publish:** `POST /v2/{name=publishers/*/items/*}:publish`.
    - **Set Published Deploy Percentage:** `POST /v2/{name=publishers/*/items/*}:setPublishedDeployPercentage`.

- **Item States:**
  - **Enums:**
    - `ITEM_STATE_UNSPECIFIED`
    - `PENDING_REVIEW`
    - `STAGED`
    - `PUBLISHED`
    - `PUBLISHED_TO_TESTERS`
    - `REJECTED`
    - `CANCELLED`.

- **Upload States:**
  - **Enums:**
    - `UPLOAD_STATE_UNSPECIFIED`
    - `SUCCEEDED`
    - `IN_PROGRESS`
    - `FAILED`
    - `NOT_FOUND`.

- **Publishing:**
  - **Publish Types:**
    - `DEFAULT_PUBLISH`
    - `STAGED_PUBLISH`.
  - **Deploy Infos:** Optional, includes desired initial rollout percentage.
  - **Skip Review:** Optional, default `false`.
  - **Block on Warnings:** Optional, default `false`.

- **Set Published Deploy Percentage:**
  - **Minimum Users:** 10,000 seven-day active users.
  - **Deploy Percentage:** Nonnegative integer between 0 and 100, must be larger than existing.

- **API V1 (Deprecated):**
  - **Support Until:** 15th October 2026.
  - **OAuth Scopes:**
    - `https://www.googleapis.com/auth/chromewebstore`
    - `https://www.googleapis.com/auth/chromewebstore.readonly`.
  - **Endpoints:**
    - **Get Item:** `GET /chromewebstore/v1.1/items/itemId?projection=DRAFT`.
    - **Insert Item:** `POST /upload/chromewebstore/v1.1/items`.
    - **Publish Item:** `POST /chromewebstore/v1.1/items/itemId/publish`.
    - **Update Item:** `PUT /upload/chromewebstore/v1.1/items/itemId` and `PUT /items/itemId`.