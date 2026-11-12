"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  info: null,
  health: null,
  jobs: [],
  jobsLoaded: false,
  polling: false,
  pollTimer: null,
  parseStatusTimer: null,
  parsing: false,
  downloadBusy: new Set(),
};

const els = {};

const ICONS = {
  video: '<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.7"/><path d="m10.3 9.3 4.6 2.7-4.6 2.7V9.3Z" fill="currentColor"/></svg>',
  audio: '<svg viewBox="0 0 24 24" fill="none"><path d="M9 17.5V6.8l9-2v10.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><ellipse cx="6.9" cy="17.6" rx="2.7" ry="2.3" stroke="currentColor" stroke-width="1.7"/><ellipse cx="15.9" cy="15.4" rx="2.7" ry="2.3" stroke="currentColor" stroke-width="1.7"/></svg>',
  thumbnail: '<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.7"/><circle cx="8.5" cy="9" r="1.6" fill="currentColor"/><path d="m5.5 17 4.2-4.6 3 3.1 2.2-2.4 3.6 3.9" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  muted: '<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.7"/><path d="m10.3 9.3 4.6 2.7-4.6 2.7V9.3Z" fill="currentColor"/><path d="m16.3 8.4 4 7.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 4v11m0 0 4-4m-4 4-4-4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 19h14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none"><path d="M3.5 7.5A1.8 1.8 0 0 1 5.3 5.7h4l2 2h7.4a1.8 1.8 0 0 1 1.8 1.8v7.2a1.8 1.8 0 0 1-1.8 1.8H5.3a1.8 1.8 0 0 1-1.8-1.8V7.5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
  cancel: '<svg viewBox="0 0 24 24" fill="none"><path d="m7 7 10 10M17 7 7 17" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none"><path d="m5.5 12.5 4 4L18.7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none"><path d="M12 4.8 20 19H4L12 4.8Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M12 9.5v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="16.3" r="1.05" fill="currentColor"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.7"/><path d="M12 11v5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="8" r="1.05" fill="currentColor"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none"><path d="M3.5 12s3.1-5.2 8.5-5.2 8.5 5.2 8.5 5.2-3.1 5.2-8.5 5.2S3.5 12 3.5 12Z" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="12" r="2.5" stroke="currentColor" stroke-width="1.6"/></svg>',
  calendar: '<svg viewBox="0 0 24 24" fill="none"><rect x="4" y="5.5" width="16" height="14" rx="2.5" stroke="currentColor" stroke-width="1.6"/><path d="M4 9.5h16M8 3.8v3.4M16 3.8v3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  layers: '<svg viewBox="0 0 24 24" fill="none"><path d="m12 4 8 4-8 4-8-4 8-4Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="m4.8 12 7.2 3.6 7.2-3.6M4.8 16l7.2 3.6 7.2-3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  [
    "parseForm", "urlInput", "pasteBtn", "parseBtn", "parseStatus", "alert", "alertTitle",
    "alertDesc", "alertDetails", "alertDetailText", "alertClose", "result", "thumb",
    "previewMedia", "durationBadge", "mediaChannel", "mediaDate", "videoTitle", "mediaMeta",
    "ytLink", "mediaId", "videoHeight", "videoFormatHint", "compatToggle", "mutedToggle",
    "videoDownloadBtn", "audioFormat", "audioQuality", "bitrateField", "audioHint",
    "audioDownloadBtn", "coverQuality", "coverMini", "coverDownloadBtn", "ffmpegNote",
    "queueList", "jobCount", "openFolderBtn", "toastStack", "helpBtn", "helpDialog",
    "helpClose", "cookieStatus", "engineChip", "engineText",
  ].forEach((id) => { els[id] = $(id); });

  els.parseForm.addEventListener("submit", (event) => {
    event.preventDefault();
    parseVideo();
  });
  els.pasteBtn.addEventListener("click", pasteFromClipboard);
  els.alertClose.addEventListener("click", hideAlert);
  els.videoHeight.addEventListener("change", () => {
    updateResolutionHint();
    updateDownloadAvailability();
  });
  els.mutedToggle.addEventListener("change", () => {
    updateResolutionHint();
    updateDownloadAvailability();
  });
  els.compatToggle.addEventListener("change", updateDownloadAvailability);
  els.audioFormat.addEventListener("change", updateAudioQuality);
  els.coverQuality.addEventListener("change", updateCoverPreview);
  els.videoDownloadBtn.addEventListener("click", () => startDownload("video"));
  els.audioDownloadBtn.addEventListener("click", () => startDownload("audio"));
  els.coverDownloadBtn.addEventListener("click", () => startDownload("thumbnail"));
  els.openFolderBtn.addEventListener("click", () => openFolder(""));
  els.queueList.addEventListener("click", onQueueClick);
  els.helpBtn.addEventListener("click", () => {
    els.helpDialog.showModal();
    document.body.classList.add("dialog-open");
  });
  els.helpClose.addEventListener("click", () => els.helpDialog.close());
  els.helpDialog.addEventListener("click", (event) => {
    if (event.target === els.helpDialog) els.helpDialog.close();
  });
  els.helpDialog.addEventListener("close", () => document.body.classList.remove("dialog-open"));
  els.thumb.addEventListener("error", () => els.previewMedia.classList.add("no-image"));
  els.coverMini.addEventListener("error", () => els.coverMini.classList.add("is-broken"));
  els.coverMini.addEventListener("load", () => els.coverMini.classList.remove("is-broken"));

  loadHealth();
  refreshJobs({ notify: false });
  const sharedUrl = new URLSearchParams(window.location.search).get("url");
  if (sharedUrl) {
    els.urlInput.value = sharedUrl;
    window.setTimeout(parseVideo, 120);
  }
}

/* ------------------------------------------------------------------ health */

async function loadHealth() {
  try {
    const health = await api("/api/health", { timeout: 8000 });
    state.health = health;
    els.engineChip.classList.remove("warn", "error");
    els.engineChip.classList.add("ok");
    els.engineText.textContent = `yt-dlp ${health.ytdlp?.version || "已就绪"}`;
    els.engineChip.title = health.ffmpeg?.available
      ? `yt-dlp ${health.ytdlp?.version || ""} · FFmpeg ${health.ffmpeg.version || ""}`
      : "未检测到 FFmpeg";

    if (health.ffmpeg?.available) {
      els.ffmpegNote.className = "engine-note ok";
      els.ffmpegNote.textContent = `FFmpeg ${health.ffmpeg.version || ""} 已就绪`;
    } else {
      els.ffmpegNote.className = "engine-note warn";
      els.ffmpegNote.textContent = "FFmpeg 未安装";
      showAlert(
        "warn",
        "没有找到 FFmpeg",
        "视频合并（1080p 以上）和音频转换需要 FFmpeg。可以把 ffmpeg.exe 放到程序目录的 bin 文件夹，安装后重启应用。封面和「仅画面」仍可下载。"
      );
    }

    if (health.cookies) {
      els.cookieStatus.className = "dialog-note ok";
      els.cookieStatus.textContent = "已检测到 cookies.txt，登录态可用。";
    } else {
      els.cookieStatus.className = "dialog-note";
      els.cookieStatus.textContent = "未检测到 cookies.txt；公开视频通常不需要。";
    }
    updateDownloadAvailability();
  } catch (error) {
    els.engineChip.classList.remove("ok", "warn");
    els.engineChip.classList.add("error");
    els.engineText.textContent = "本地服务未连接";
    showAlert(
      "error",
      "无法连接本地下载服务",
      "请确认运行窗口没有关闭，然后刷新此页面。如果刚启动，请稍等两秒。",
      describeError(error)
    );
  }
}

/* ------------------------------------------------------------------- parse */

async function parseVideo() {
  if (state.parsing) return;
  const url = els.urlInput.value.trim();
  if (!url) {
    els.urlInput.focus();
    toast("请先粘贴 YouTube 视频链接。", "info");
    return;
  }

  state.parsing = true;
  state.info = null;
  els.result.hidden = true;
  hideAlert();
  setParseLoading(true);
  els.parseStatus.hidden = false;
  els.parseStatus.textContent = "正在与 YouTube 通信，解析视频信息…通常需要 2–10 秒";

  try {
    const info = await api("/api/info", {
      method: "POST",
      body: { url },
      timeout: 95000,
    });
    state.info = info;
    renderInfo(info);
    els.result.hidden = false;
    els.result.classList.remove("reveal");
    void els.result.offsetWidth;
    els.result.classList.add("reveal");
    els.parseStatus.textContent = `解析完成，找到 ${info.resolutions?.length || 0} 种视频清晰度和 ${info.thumbnails?.length || 0} 种封面尺寸。`;
    if (state.parseStatusTimer) window.clearTimeout(state.parseStatusTimer);
    state.parseStatusTimer = window.setTimeout(() => { els.parseStatus.hidden = true; }, 3200);
    window.setTimeout(() => {
      const top = els.result.getBoundingClientRect().top + window.scrollY - 82;
      window.scrollTo({ top, behavior: "smooth" });
    }, 80);
  } catch (error) {
    els.parseStatus.hidden = true;
    if (state.parseStatusTimer) window.clearTimeout(state.parseStatusTimer);
    const payload = error.payload || {};
    showAlert(
      "error",
      payload.error || "解析失败",
      payload.hint || "请检查链接是否有效，然后重试。",
      payload.detail || describeError(error)
    );
    toast(payload.error || "解析失败，请查看提示。", "error");
  } finally {
    state.parsing = false;
    setParseLoading(false);
  }
}

function setParseLoading(loading) {
  els.parseBtn.disabled = loading;
  els.parseBtn.classList.toggle("is-loading", loading);
  els.parseBtn.querySelector(".btn-label").textContent = loading ? "解析中" : "解析视频";
  els.urlInput.disabled = loading;
  els.pasteBtn.disabled = loading;
}

function renderInfo(info) {
  els.compatToggle.checked = true;
  els.mutedToggle.checked = false;
  els.previewMedia.classList.remove("no-image");
  els.thumb.src = info.thumbnail || "";
  els.thumb.alt = `${info.title} 的封面`;
  els.durationBadge.textContent = formatDuration(info.duration) || "--:--";
  els.mediaChannel.textContent = info.uploader || "未知频道";
  els.mediaDate.textContent = info.upload_date || "日期未知";
  els.videoTitle.textContent = info.title || "未命名视频";
  els.mediaId.textContent = info.id ? `ID ${info.id}` : "";
  els.ytLink.href = safeYouTubeUrl(info.webpage_url, info.id);

  els.mediaMeta.replaceChildren();
  if (info.view_count > 0) appendMeta(ICONS.eye, `${formatNumber(info.view_count)} 次观看`);
  if (info.like_count > 0) appendMeta(ICONS.check, `${formatNumber(info.like_count)} 赞`);
  appendMeta(ICONS.layers, `${info.resolutions?.length || 0} 种清晰度`);
  if (info.has_audio === false) appendMeta(ICONS.info, "无音轨");

  els.videoHeight.replaceChildren();
  els.videoHeight.disabled = false;
  const resolutions = Array.isArray(info.resolutions) ? info.resolutions : [];
  if (resolutions.length) {
    els.videoHeight.add(new Option("最佳画质 · 自动选择最高", "best"));
    for (const item of resolutions) {
      const fps = item.fps ? `${Math.round(item.fps)} fps` : "";
      const codec = item.codec || "";
      const hdr = item.hdr ? "HDR" : "";
      const details = [fps, codec, hdr].filter(Boolean).join(" · ");
      els.videoHeight.add(new Option(details ? `${item.label}  ·  ${details}` : item.label, String(item.height)));
    }
    els.videoHeight.value = String(info.default_height || "best");
    if (!els.videoHeight.value) els.videoHeight.value = "best";
    updateResolutionHint();
  } else {
    els.videoHeight.add(new Option("未找到可用的视频流", ""));
    els.videoHeight.disabled = true;
    els.videoFormatHint.textContent = "当前视频没有解析到可下载的视频流。";
  }

  updateAudioQuality();
  els.audioHint.textContent = info.has_audio === false
    ? "该视频没有音轨，无法提取音频。"
    : "音频将从视频中分离，原始音轨可选不转码。";

  els.coverQuality.replaceChildren();
  const thumbs = Array.isArray(info.thumbnails) ? info.thumbnails : [];
  for (const item of thumbs) {
    els.coverQuality.add(new Option(`${item.label} · ${item.detail}`, item.id));
  }
  els.coverQuality.value = thumbs.some((item) => item.id === "maxres") ? "maxres" : (thumbs[0]?.id || "hq");
  updateCoverPreview();
  updateDownloadAvailability();
}

function appendMeta(icon, text) {
  const span = document.createElement("span");
  span.innerHTML = icon;
  span.appendChild(document.createTextNode(text));
  els.mediaMeta.appendChild(span);
}

/* ------------------------------------------------------------------ options */

function updateAudioQuality() {
  const presets = {
    mp3: [320, 256, 192, 128],
    m4a: [256, 192, 128],
    opus: [192, 160, 128],
    wav: [],
    best: [],
  };
  const format = els.audioFormat.value;
  const values = presets[format] || presets.mp3;
  els.audioQuality.replaceChildren();
  if (!values.length) {
    els.audioQuality.add(new Option(format === "wav" ? "无损 · 无需设置" : "不转码 · 无需设置", ""));
    els.audioQuality.disabled = true;
    els.bitrateField.classList.add("is-disabled");
  } else {
    for (const value of values) {
      els.audioQuality.add(new Option(`${value} kbps${value === 320 ? " · 高码率" : ""}`, String(value)));
    }
    els.audioQuality.value = values.includes(192) ? "192" : String(values[0]);
    els.audioQuality.disabled = false;
    els.bitrateField.classList.remove("is-disabled");
  }
}

function updateResolutionHint() {
  if (!state.info) return;
  const resolutions = state.info.resolutions || [];
  if (els.videoHeight.value === "best" || !resolutions.length) {
    els.videoFormatHint.textContent = resolutions.length
      ? `自动选择最高可用清晰度 · 共 ${resolutions.length} 种`
      : "当前视频没有解析到可下载的视频流。";
    return;
  }
  const selected = resolutions.find((item) => String(item.height) === els.videoHeight.value);
  if (!selected) return;
  const details = [
    selected.fps ? `${Math.round(selected.fps)} fps` : "",
    selected.codec || "",
    selected.hdr ? "HDR" : "",
    selected.size_estimate ? `视频流约 ${formatBytes(selected.size_estimate)}` : "",
  ].filter(Boolean);
  const audioNote = els.mutedToggle.checked
    ? "仅画面"
    : state.info.has_audio === false
      ? "无音轨"
      : "另含音轨";
  els.videoFormatHint.textContent = `${details.join(" · ")} · ${audioNote}`;
}

function updateCoverPreview() {
  if (!state.info) return;
  const quality = els.coverQuality.value;
  const item = (state.info.thumbnails || []).find((thumb) => thumb.id === quality);
  if (item) {
    els.coverMini.classList.remove("is-broken");
    els.coverMini.src = item.url;
    els.coverMini.alt = `封面预览（${item.label}）`;
  }
}

function updateDownloadAvailability() {
  if (!state.info) return;
  const ffmpegOk = state.health?.ffmpeg?.available !== false;
  const hasVideo = (state.info.resolutions || []).length > 0;
  const muted = els.mutedToggle.checked;
  els.videoDownloadBtn.disabled = !hasVideo || (!ffmpegOk && !muted);
  els.audioDownloadBtn.disabled = state.info.has_audio === false || !ffmpegOk;
  els.coverDownloadBtn.disabled = false;
  els.videoDownloadBtn.title = !ffmpegOk && !muted
    ? "需要 FFmpeg 才能合并音轨；可勾选「仅画面」或安装 FFmpeg"
    : "";
}

/* ---------------------------------------------------------------- downloads */

async function startDownload(kind) {
  if (!state.info || state.downloadBusy.has(kind)) return;
  const ffmpegOk = state.health?.ffmpeg?.available !== false;
  if (kind === "audio" && !ffmpegOk) {
    toast("音频分离需要 FFmpeg，请先安装。", "error");
    return;
  }
  if (kind === "video" && !ffmpegOk && !els.mutedToggle.checked) {
    toast("合并音轨需要 FFmpeg；也可以勾选「仅画面」后下载。", "error");
    return;
  }

  const payload = {
    url: state.info.url,
    title: state.info.title,
    kind,
  };
  if (kind === "video") {
    payload.height = els.videoHeight.value === "best" ? "best" : Number(els.videoHeight.value);
    payload.compat = els.compatToggle.checked;
    payload.muted = els.mutedToggle.checked;
  } else if (kind === "audio") {
    payload.audio_format = els.audioFormat.value;
    if (!els.audioQuality.disabled && els.audioQuality.value) {
      payload.audio_quality = Number(els.audioQuality.value);
    }
  } else if (kind === "thumbnail") {
    payload.thumb_quality = els.coverQuality.value;
  }

  const button = kind === "video" ? els.videoDownloadBtn : kind === "audio" ? els.audioDownloadBtn : els.coverDownloadBtn;
  state.downloadBusy.add(kind);
  setButtonLoading(button, true);

  try {
    const result = await api("/api/download", { method: "POST", body: payload, timeout: 20000 });
    const spec = result.job?.spec ? `（${result.job.spec}）` : "";
    toast(`已加入下载队列${spec}`, "success");
    await refreshJobs({ notify: false });
  } catch (error) {
    const payloadError = error.payload || {};
    showAlert(
      "error",
      payloadError.error || "无法开始下载",
      payloadError.hint || "请稍后重试。",
      payloadError.detail || describeError(error)
    );
    toast(payloadError.error || "无法开始下载。", "error");
  } finally {
    state.downloadBusy.delete(kind);
    setButtonLoading(button, false);
  }
}

function setButtonLoading(button, loading) {
  if (!button) return;
  button.classList.toggle("is-loading", loading);
  button.disabled = loading;
  if (!loading) updateDownloadAvailability();
}

/* -------------------------------------------------------------------- queue */

async function refreshJobs({ notify = true } = {}) {
  if (state.polling) return;
  state.polling = true;
  try {
    const data = await api("/api/jobs", { timeout: 8000 });
    handleJobs(Array.isArray(data.jobs) ? data.jobs : [], notify);
  } catch (error) {
    if (notify && state.jobsLoaded) {
      // A dropped poll is not worth a toast; the next tick usually recovers.
      console.debug("job poll failed", error);
    }
  } finally {
    state.polling = false;
    schedulePoll();
  }
}

function schedulePoll() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  const active = state.jobs.some((job) => ["queued", "downloading", "processing", "cancelling"].includes(job.status));
  const delay = document.hidden ? 4500 : active ? 850 : 2400;
  state.pollTimer = window.setTimeout(() => refreshJobs(), delay);
}

function handleJobs(jobs, notify) {
  const previous = new Map(state.jobs.map((job) => [job.id, job]));
  if (notify && state.jobsLoaded) {
    for (const job of jobs) {
      const old = previous.get(job.id);
      if (!old) continue;
      if (old.status !== job.status) {
        if (job.status === "completed") {
          toast(`下载完成：${job.filename || job.title}`, "success");
        } else if (job.status === "failed") {
          toast(job.error || `「${job.title}」下载失败`, "error");
        }
      }
    }
  }
  state.jobs = jobs;
  state.jobsLoaded = true;
  renderJobs();
  const active = jobs.filter((job) => ["queued", "downloading", "processing", "cancelling"].includes(job.status)).length;
  document.title = active ? `(${active}) 下载中 · YT Grab` : "YT Grab · YouTube 视频 / 音频 / 封面下载器";
}

function renderJobs() {
  els.jobCount.textContent = String(state.jobs.length);
  if (!state.jobs.length) {
    els.queueList.innerHTML = `
      <div class="queue-empty">
        <span class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none"><path d="M4 7.2A2.2 2.2 0 0 1 6.2 5h3.5l1.8 2h6.3A2.2 2.2 0 0 1 20 9.2v8.6A2.2 2.2 0 0 1 17.8 20H6.2A2.2 2.2 0 0 1 4 17.8V7.2Z" stroke="currentColor" stroke-width="1.5"/><path d="M8.5 13.2h7M12 9.8v6.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
        </span>
        <p>队列还是空的</p>
        <span>解析视频后，选择视频、音频或封面开始下载。</span>
      </div>`;
    return;
  }
  els.queueList.innerHTML = state.jobs.map(renderJob).join("");
}

function renderJob(job) {
  const kind = ["video", "audio", "thumbnail", "muted"].includes(job.kind) ? job.kind : "video";
  const active = ["queued", "downloading", "processing", "cancelling"].includes(job.status);
  const progress = clamp(Number(job.progress) || 0, 0, 100);
  const meta = jobMeta(job);
  const isDone = job.status === "completed";
  const isFailed = job.status === "failed";
  const icon = ICONS[kind] || ICONS.video;
  const actions = active
    ? `<button class="job-btn danger" type="button" data-action="cancel" data-id="${escapeHtml(job.id)}" title="取消下载" aria-label="取消下载">${ICONS.cancel}</button>`
    : isDone
      ? `<button class="job-btn" type="button" data-action="folder" data-id="${escapeHtml(job.id)}" title="打开所在文件夹" aria-label="打开所在文件夹">${ICONS.folder}</button>`
      : "";

  const errorBlock = isFailed
    ? `<div class="job-error">
        <div>${escapeHtml(job.error || "下载失败")}</div>
        ${job.error_hint ? `<div>${escapeHtml(job.error_hint)}</div>` : ""}
        ${job.error_detail ? `<details><summary>技术详情</summary><pre>${escapeHtml(job.error_detail)}</pre></details>` : ""}
      </div>`
    : "";

  return `<article class="queue-item job-${kind} status-${escapeHtml(job.status)}">
    <span class="job-icon" aria-hidden="true">${icon}</span>
    <div class="job-body">
      <div class="job-topline">
        <span class="job-title" title="${escapeHtml(job.title)}">${escapeHtml(job.title)}</span>
        <span class="job-spec">${escapeHtml(job.spec || "")}</span>
      </div>
      <div class="job-meta">${meta}</div>
      ${errorBlock}
    </div>
    <div class="job-actions">${actions}</div>
    <div class="job-progress"><progress max="100" value="${isDone ? 100 : progress}" aria-label="下载进度 ${Math.round(progress)}%"></progress></div>
  </article>`;
}

function statusInfo(job) {
  const labels = {
    queued: "排队中",
    downloading: "下载中",
    processing: "正在处理",
    cancelling: "正在取消",
    completed: "已完成",
    failed: "下载失败",
    cancelled: "已取消",
  };
  const css = job.status === "completed" ? "done" : job.status === "failed" ? "error" : job.status === "cancelled" ? "" : "active";
  return { text: labels[job.status] || job.status, cls: css };
}

function jobMeta(job) {
  const info = statusInfo(job);
  const parts = [`<span class="job-status ${info.cls}">${info.text}</span>`];

  if (job.status === "downloading") {
    parts.push(`<span>${Math.round(job.progress || 0)}%</span>`);
    if (job.speed > 0) parts.push(`<span>${formatBytes(job.speed)}/s</span>`);
    if (job.eta) parts.push(`<span>剩余 ${formatEta(job.eta)}</span>`);
    else if (job.total > 0) parts.push(`<span>${formatBytes(job.downloaded)} / ${formatBytes(job.total)}</span>`);
  } else if (job.status === "processing") {
    parts.push("<span>合并音轨 / 转换格式，请稍候</span>");
  } else if (job.status === "queued") {
    parts.push("<span>等待空闲下载位</span>");
  } else if (job.status === "completed") {
    const size = job.files?.[0]?.size || 0;
    if (size) parts.push(`<span>${formatBytes(size)}</span>`);
    if (job.filename) parts.push(`<span title="${escapeHtml(job.filename)}">${escapeHtml(job.filename)}</span>`);
  } else if (job.status === "cancelled") {
    parts.push("<span>文件未保留</span>");
  } else if (job.status === "failed") {
    parts.push("<span>详见下方错误信息</span>");
  }

  return parts.join('<span class="meta-sep"></span>');
}

async function onQueueClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const id = button.dataset.id;
  if (action === "cancel") {
    await cancelJob(id);
  } else if (action === "folder") {
    await openFolder(id);
  }
}

async function cancelJob(id) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", timeout: 8000 });
    toast("已取消下载。", "info");
    await refreshJobs({ notify: false });
  } catch (error) {
    toast(describeError(error), "error");
  }
}

async function openFolder(jobId) {
  try {
    await api("/api/open-folder", { method: "POST", body: { job_id: jobId || "" }, timeout: 8000 });
  } catch (error) {
    toast(describeError(error), "error");
  }
}

/* -------------------------------------------------------------------- alerts */

function showAlert(kind, title, description, detail) {
  els.alert.hidden = false;
  els.alert.classList.toggle("warn", kind === "warn");
  els.alertTitle.textContent = title || "提示";
  els.alertDesc.textContent = description || "";
  if (detail) {
    els.alertDetails.hidden = false;
    els.alertDetailText.textContent = detail;
  } else {
    els.alertDetails.hidden = true;
    els.alertDetailText.textContent = "";
  }
}

function hideAlert() {
  els.alert.hidden = true;
  els.alert.classList.remove("warn");
}

function toast(message, kind = "success") {
  const item = document.createElement("div");
  item.className = `toast ${kind === "error" ? "error" : kind === "info" ? "info" : ""}`;
  const icon = document.createElement("span");
  icon.className = "toast-icon";
  icon.innerHTML = kind === "error" ? ICONS.alert : kind === "info" ? ICONS.info : ICONS.check;
  const copy = document.createElement("span");
  copy.textContent = message;
  item.append(icon, copy);
  els.toastStack.appendChild(item);

  while (els.toastStack.children.length > 4) {
    els.toastStack.firstElementChild.remove();
  }
  window.setTimeout(() => {
    item.classList.add("removing");
    window.setTimeout(() => item.remove(), 260);
  }, 4600);
}

/* -------------------------------------------------------------------- input */

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      els.urlInput.value = text.trim();
      els.urlInput.focus();
      els.urlInput.select();
      toast("已从剪贴板粘贴链接。", "info");
    } else {
      els.urlInput.focus();
      toast("剪贴板是空的，请手动粘贴。", "info");
    }
  } catch {
    els.urlInput.focus();
    toast("浏览器未授权读取剪贴板，请按 Ctrl+V 粘贴。", "info");
  }
}

/* ------------------------------------------------------------------- helpers */

async function api(path, { method = "GET", body = null, timeout = 20000 } = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : { Accept: "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
    const text = await response.text();
    let data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { error: text.slice(0, 300) };
      }
    }
    if (!response.ok) {
      const error = new Error(data.error || `请求失败（HTTP ${response.status}）`);
      error.payload = data;
      error.status = response.status;
      throw error;
    }
    return data;
  } finally {
    window.clearTimeout(timer);
  }
}

function describeError(error) {
  if (!error) return "未知错误";
  if (error.name === "AbortError") return "请求超时，请检查网络或稍后重试。";
  if (error.payload?.detail) return error.payload.detail;
  return error.message || String(error);
}

function safeYouTubeUrl(value, id) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && /(^|\.)youtube\.com$/i.test(url.hostname)) return url.href;
  } catch {
    // fall through
  }
  return `https://www.youtube.com/watch?v=${encodeURIComponent(id || "")}`;
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 100 || index === 0 ? Math.round(size) : size.toFixed(1)} ${units[index]}`;
}

function formatEta(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (!total) return "";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatNumber(value) {
  const number = Number(value) || 0;
  try {
    return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(number);
  } catch {
    return number.toLocaleString("zh-CN");
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
