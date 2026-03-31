/**
 * listing_content_script.js — AI店长 商品导入内容脚本
 * 支持 1688 / 拼多多 商品详情页一键导入
 */

(function () {
  'use strict';

  // 防重复注入
  if (window.__aIDZListingInjected) return;
  window.__aIDZListingInjected = true;

  /* ═══════════════════ 平台检测 ═══════════════════ */
  function detectPlatform() {
    const host = location.hostname;
    if (host.includes('1688.com')) return 'alibaba';
    if (host.includes('pinduoduo.com') || host.includes('yangkeduo.com')) return 'pdd';
    return null;
  }

  const PLATFORM = detectPlatform();
  if (!PLATFORM) return; // 不是目标平台，退出

  /* ═══════════════════ DOM 辅助函数 ═══════════════════ */

  /**
   * 安全获取元素文本，支持多个选择器作为 fallback
   */
  function safeText(...selectors) {
    for (const sel of selectors) {
      try {
        const el = document.querySelector(sel);
        const text = el?.textContent?.trim() || el?.innerText?.trim();
        if (text) return text;
      } catch (_) { /* 忽略无效选择器 */ }
    }
    return '';
  }

  /**
   * 从包含关键词的元素中提取对应值
   */
  function _extractFromDetail(keyword) {
    const selectors = [
      '.detail-info td',
      '.obj-content li',
      '[class*="attr"] td',
      '[class*="attr"] li',
      '[class*="Attr"] td',
      '[class*="Attr"] li',
      '.product-prop li',
      '.prop-item',
    ];
    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (el.textContent?.includes(keyword)) {
            return el.textContent
              .replace(keyword, '')
              .replace(/[:：\s]/g, ' ')
              .trim()
              .split(/\s+/)
              .filter(Boolean)
              .join(' ');
          }
        }
      } catch (_) { /* 忽略 */ }
    }
    return '';
  }

  /**
   * 提取商品规格/属性
   */
  function _extractSpecs() {
    const specs = {};
    const rowSelectors = [
      '.obj-sku .obj-content li',
      '[class*="attr"] tr',
      '[class*="Attr"] tr',
      '.detail-info tr',
      '.product-prop li',
      '.prop-item',
      '.goods-props-item',
    ];
    for (const sel of rowSelectors) {
      try {
        document.querySelectorAll(sel).forEach((el) => {
          const label =
            el.querySelector('.name, th, [class*="name"], [class*="label"]')?.textContent?.trim() ||
            el.querySelector('dt')?.textContent?.trim();
          const value =
            el.querySelector('.value, td, [class*="value"], [class*="val"]')?.textContent?.trim() ||
            el.querySelector('dd')?.textContent?.trim();
          if (label && value && label.length < 30) {
            specs[label] = value;
          }
        });
      } catch (_) { /* 忽略 */ }
    }
    return specs;
  }

  /**
   * 提取图片列表（去重 + 过滤无效）
   */
  function _extractImages(selectors) {
    const seen = new Set();
    const imgs = [];
    for (const sel of selectors) {
      try {
        document.querySelectorAll(sel).forEach((img) => {
          const src = img.src || img.dataset.src || img.dataset.lazySrc || img.getAttribute('data-lazy');
          if (src && src.startsWith('http') && !seen.has(src)) {
            seen.add(src);
            imgs.push(src);
          }
        });
      } catch (_) { /* 忽略 */ }
    }
    return imgs;
  }

  /* ═══════════════════ 1688 提取 ═══════════════════ */
  function extract1688() {
    const title = safeText(
      '.title-text',
      'h1[class*="title"]',
      '[class*="title-text"]',
      '[class*="Title"]',
      'h1'
    );

    const price = safeText(
      '.price-text',
      '[class*="price-text"]',
      '[class*="Price"]',
      '.price em',
      '.step-price-item .price'
    );

    const images = _extractImages([
      '.detail-gallery-turn img',
      '[class*="gallery"] img',
      '[class*="Gallery"] img',
      '.img-gallery img',
      '.item-gallery img',
      '.small-img-list img',
    ]);

    const minOrder = safeText(
      '[class*="step-price"]',
      '[class*="min-order"]',
      '[class*="minOrder"]',
      '.step-price-item'
    );

    const shopName = safeText(
      '[class*="shop-name"]',
      '.company-name',
      '[class*="companyName"]',
      '[class*="shopName"]',
      '.seller-name'
    );

    const description = (() => {
      const descEl =
        document.querySelector('.desc-lazyload-container') ||
        document.querySelector('[class*="detail-desc"]') ||
        document.querySelector('[class*="DetailDesc"]') ||
        document.querySelector('.detail-content');
      return descEl?.textContent?.trim()?.slice(0, 2000) || '';
    })();

    return {
      source_platform: 'alibaba',
      source_url: window.location.href,
      title,
      price,
      images,
      specs: _extractSpecs(),
      brand: _extractFromDetail('品牌') || _extractFromDetail('Brand') || '',
      barcode: _extractFromDetail('条形码') || _extractFromDetail('EAN') || _extractFromDetail('GTIN') || '',
      min_order: minOrder,
      shop_name: shopName,
      description,
      // 医疗器械特有字段
      registration_cert: _extractFromDetail('注册证') || _extractFromDetail('备案') || _extractFromDetail('注册备案') || '',
      device_class: _extractFromDetail('分类') || _extractFromDetail('类别') || '',
    };
  }

  /* ═══════════════════ 拼多多提取 ═══════════════════ */
  function extractPDD() {
    const title = safeText(
      '.goods-name',
      '[class*="goodsName"]',
      '[class*="GoodsName"]',
      '[class*="goods-name"]',
      'h1[class*="title"]',
      'h1'
    );

    const price = safeText(
      '.goods-price',
      '[class*="goodsPrice"]',
      '[class*="Price"]',
      '[class*="price"]',
      '.price-text',
      '.current-price'
    );

    const images = _extractImages([
      '.goods-gallery img',
      '[class*="gallery"] img',
      '[class*="Gallery"] img',
      '[class*="swiper"] img',
      '.image-slider img',
    ]);

    const shopName = safeText(
      '[class*="shop-name"]',
      '[class*="shopName"]',
      '[class*="StoreName"]',
      '.store-name',
      '.merchant-name'
    );

    const description = (() => {
      const descEl =
        document.querySelector('[class*="detail-desc"]') ||
        document.querySelector('[class*="DetailDesc"]') ||
        document.querySelector('[class*="goodsDetail"]') ||
        document.querySelector('.goods-detail');
      return descEl?.textContent?.trim()?.slice(0, 2000) || '';
    })();

    return {
      source_platform: 'pdd',
      source_url: window.location.href,
      title,
      price,
      images,
      specs: _extractSpecs(),
      brand: _extractFromDetail('品牌') || '',
      barcode: _extractFromDetail('条形码') || _extractFromDetail('EAN') || '',
      min_order: '',
      shop_name: shopName,
      description,
      registration_cert: _extractFromDetail('注册证') || _extractFromDetail('备案') || '',
      device_class: _extractFromDetail('分类') || '',
    };
  }

  /* ═══════════════════ 提取入口 ═══════════════════ */
  function extractProductData() {
    try {
      return PLATFORM === 'alibaba' ? extract1688() : extractPDD();
    } catch (err) {
      console.error('[AI店长] 商品提取失败:', err);
      return null;
    }
  }

  /* ═══════════════════ 构建面板 UI ═══════════════════ */
  function buildPanel() {
    // 创建悬浮按钮
    const fab = document.createElement('button');
    fab.id = 'aidz-listing-fab';
    fab.innerHTML = '📤<br>导<br>入<br>AI<br>店<br>长';
    fab.title = '一键导入到 AI店长';
    document.body.appendChild(fab);

    // 创建侧边面板
    const panel = document.createElement('div');
    panel.id = 'aidz-listing-panel';
    panel.innerHTML = `
      <div class="aidz-lp-header">
        <h2>📦 商品导入 AI店长</h2>
        <span class="aidz-lp-platform-badge" id="aidz-lp-platform">
          ${PLATFORM === 'alibaba' ? '1688' : '拼多多'}
        </span>
        <button class="aidz-lp-close" id="aidz-lp-close" title="关闭">✕</button>
      </div>

      <div class="aidz-lp-body">
        <!-- 加载视图 -->
        <div class="aidz-lp-view active" id="aidz-lp-view-loading">
          <div class="aidz-lp-loading">
            <div class="aidz-lp-spinner"></div>
            <div>正在提取商品信息…</div>
          </div>
        </div>

        <!-- 错误视图 -->
        <div class="aidz-lp-view" id="aidz-lp-view-error">
          <div class="aidz-lp-error-box">
            <div class="aidz-lp-error-title">⚠️ 提取遇到问题</div>
            <div id="aidz-lp-error-msg">部分信息未能自动提取，请手动补充后再导入。</div>
          </div>
          <div style="margin-top:10px;font-size:12px;color:#888">
            您仍可在下方手动填写后点击「确认导入」。
          </div>
        </div>

        <!-- 商品信息表单视图 -->
        <div class="aidz-lp-view" id="aidz-lp-view-form">
          <div class="aidz-lp-section">
            <div class="aidz-lp-section-title">基本信息</div>
            <div class="aidz-lp-field">
              <label>商品标题 *</label>
              <input type="text" id="aidz-lp-title" placeholder="商品名称">
            </div>
            <div class="aidz-lp-field">
              <label>价格</label>
              <input type="text" id="aidz-lp-price" placeholder="例：¥99.00">
            </div>
            <div class="aidz-lp-field">
              <label>品牌</label>
              <input type="text" id="aidz-lp-brand" placeholder="品牌名称">
            </div>
            <div class="aidz-lp-field">
              <label>店铺名称</label>
              <input type="text" id="aidz-lp-shop" placeholder="供应商/店铺">
            </div>
          </div>

          <div class="aidz-lp-section">
            <div class="aidz-lp-section-title">图片</div>
            <div id="aidz-lp-images-container">
              <div style="color:#aaa;font-size:12px">未找到图片</div>
            </div>
          </div>

          <div class="aidz-lp-section">
            <div class="aidz-lp-section-title">规格 / 属性</div>
            <div class="aidz-lp-specs-box" id="aidz-lp-specs">
              <div style="color:#aaa">未提取到规格</div>
            </div>
          </div>

          <div class="aidz-lp-section">
            <div class="aidz-lp-section-title">更多信息</div>
            <div class="aidz-lp-field">
              <label>条形码 / EAN</label>
              <input type="text" id="aidz-lp-barcode" placeholder="条形码或EAN">
            </div>
            <div class="aidz-lp-field">
              <label>起订量</label>
              <input type="text" id="aidz-lp-minorder" placeholder="最小起订量">
            </div>
            <div class="aidz-lp-field">
              <label>注册证 / 备案号（医疗器械）</label>
              <input type="text" id="aidz-lp-regcert" placeholder="注册证编号">
            </div>
            <div class="aidz-lp-field">
              <label>产品类别</label>
              <input type="text" id="aidz-lp-class" placeholder="产品分类">
            </div>
            <div class="aidz-lp-field">
              <label>商品描述</label>
              <textarea id="aidz-lp-desc" placeholder="商品详情描述（可留空）" rows="3"></textarea>
            </div>
          </div>
        </div>

        <!-- 处理进度视图 -->
        <div class="aidz-lp-view" id="aidz-lp-view-progress">
          <div class="aidz-lp-progress-wrap">
            <div class="aidz-lp-progress-step">
              <span class="aidz-lp-step-icon">📤</span>
              <div class="aidz-lp-step-text">
                <div class="step-label">正在上传商品数据</div>
                <div class="step-desc">数据已提交到 AI店长，等待处理…</div>
              </div>
            </div>
            <div class="aidz-lp-progress-bar-wrap">
              <div class="aidz-lp-progress-bar" id="aidz-lp-pbar" style="width:15%"></div>
            </div>
            <div class="aidz-lp-progress-step">
              <span class="aidz-lp-step-icon">🤖</span>
              <div class="aidz-lp-step-text">
                <div class="step-label">AI 正在处理</div>
                <div class="step-desc" id="aidz-lp-progress-msg">AI 正在分析商品信息并生成上架内容…</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 完成视图 -->
        <div class="aidz-lp-view" id="aidz-lp-view-done">
          <div class="aidz-lp-done-box">
            <div class="aidz-lp-done-icon">🎉</div>
            <div class="aidz-lp-done-title">导入成功！</div>
            <div class="aidz-lp-done-desc" id="aidz-lp-done-desc">
              商品已成功导入 AI店长，可前往管理后台查看。
            </div>
          </div>
          <div style="font-size:12px;color:#888;margin-bottom:12px;line-height:1.6">
            AI店长将根据商品信息自动生成商品标题、描述、标签等内容。
          </div>
        </div>
      </div>

      <div class="aidz-lp-footer">
        <div class="aidz-lp-status-msg" id="aidz-lp-status"></div>
        <button class="aidz-lp-btn-primary" id="aidz-lp-confirm" style="display:none">
          ✅ 确认导入
        </button>
        <button class="aidz-lp-btn-secondary" id="aidz-lp-goto" style="display:none">
          🔗 前往管理后台查看
        </button>
        <button class="aidz-lp-btn-secondary" id="aidz-lp-retry" style="display:none">
          🔄 重新提取
        </button>
      </div>
    `;
    document.body.appendChild(panel);
    return { fab, panel };
  }

  /* ═══════════════════ 填充表单 ═══════════════════ */
  function fillForm(data) {
    if (!data) return;

    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el && val) el.value = val;
    };

    set('aidz-lp-title', data.title);
    set('aidz-lp-price', data.price);
    set('aidz-lp-brand', data.brand);
    set('aidz-lp-shop', data.shop_name);
    set('aidz-lp-barcode', data.barcode);
    set('aidz-lp-minorder', data.min_order);
    set('aidz-lp-regcert', data.registration_cert);
    set('aidz-lp-class', data.device_class);
    set('aidz-lp-desc', data.description);

    // 图片预览
    const imgContainer = document.getElementById('aidz-lp-images-container');
    if (imgContainer && data.images?.length > 0) {
      const wrap = document.createElement('div');
      wrap.className = 'aidz-lp-images-wrap';
      const showCount = Math.min(data.images.length, 8);
      for (let i = 0; i < showCount; i++) {
        const img = document.createElement('img');
        img.className = 'aidz-lp-thumb';
        img.src = data.images[i];
        img.alt = `图片 ${i + 1}`;
        img.onerror = () => { img.style.display = 'none'; };
        wrap.appendChild(img);
      }
      if (data.images.length > showCount) {
        const more = document.createElement('span');
        more.className = 'aidz-lp-image-count';
        more.textContent = `+${data.images.length - showCount} 张`;
        wrap.appendChild(more);
      }
      imgContainer.innerHTML = '';
      imgContainer.appendChild(wrap);
    }

    // 规格展示
    const specsEl = document.getElementById('aidz-lp-specs');
    if (specsEl && data.specs && Object.keys(data.specs).length > 0) {
      specsEl.innerHTML = Object.entries(data.specs)
        .slice(0, 20)
        .map(([k, v]) => `
          <div class="aidz-lp-specs-row">
            <span class="lp-spec-key">${escapeHtml(k)}：</span>
            <span class="lp-spec-val">${escapeHtml(v)}</span>
          </div>
        `)
        .join('');
    }
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  /* ═══════════════════ 视图切换 ═══════════════════ */
  function showView(viewId) {
    document.querySelectorAll('.aidz-lp-view').forEach((v) => v.classList.remove('active'));
    const target = document.getElementById(viewId);
    if (target) target.classList.add('active');
  }

  function setStatus(msg, type = '') {
    const el = document.getElementById('aidz-lp-status');
    if (!el) return;
    el.textContent = msg;
    el.className = 'aidz-lp-status-msg' + (type ? ` ${type}` : '');
  }

  function showBtn(id, visible) {
    const el = document.getElementById(id);
    if (el) el.style.display = visible ? '' : 'none';
  }

  /* ═══════════════════ 从表单收集数据 ═══════════════════ */
  function collectFormData(rawData) {
    const get = (id) => document.getElementById(id)?.value?.trim() || '';
    return {
      ...rawData,
      title: get('aidz-lp-title'),
      price: get('aidz-lp-price'),
      brand: get('aidz-lp-brand'),
      shop_name: get('aidz-lp-shop'),
      barcode: get('aidz-lp-barcode'),
      min_order: get('aidz-lp-minorder'),
      registration_cert: get('aidz-lp-regcert'),
      device_class: get('aidz-lp-class'),
      description: get('aidz-lp-desc'),
    };
  }

  /* ═══════════════════ 轮询任务状态 ═══════════════════ */
  let _pollTimer = null;
  let _pollCount = 0;
  const MAX_POLL_COUNT = 60; // 最多轮询 60 次 (约 2 分钟)
  const POLL_INTERVAL_MS = 2000;

  function startPolling(taskId, chatBase) {
    _pollCount = 0;
    _pollTimer && clearTimeout(_pollTimer);

    function poll() {
      if (_pollCount >= MAX_POLL_COUNT) {
        setStatus('处理超时，请前往管理后台查看结果', 'error');
        showBtn('aidz-lp-goto', true);
        return;
      }
      _pollCount++;

      const progress = Math.min(15 + (_pollCount / MAX_POLL_COUNT) * 80, 95);
      const pbar = document.getElementById('aidz-lp-pbar');
      if (pbar) pbar.style.width = progress + '%';

      chrome.runtime.sendMessage(
        { type: 'LISTING_STATUS', taskId },
        (result) => {
          if (chrome.runtime.lastError) {
            setStatus('插件通信失败，请刷新页面重试', 'error');
            showBtn('aidz-lp-goto', true);
            return;
          }
          if (!result?.success) {
            // 非致命错误，继续轮询
            _pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
            return;
          }

          const status = result.status || result.task_status || '';
          const progressMsg = document.getElementById('aidz-lp-progress-msg');

          if (status === 'completed' || status === 'done' || status === 'success') {
            // 任务完成
            const pbar2 = document.getElementById('aidz-lp-pbar');
            if (pbar2) pbar2.style.width = '100%';

            // 保存导入记录
            _saveImportRecord({
              title: document.getElementById('aidz-lp-title')?.value || '未知商品',
              platform: PLATFORM,
              status: 'completed',
              taskId,
              chatBase,
              url: window.location.href,
              time: Date.now(),
            });

            showView('aidz-lp-view-done');
            const doneDesc = document.getElementById('aidz-lp-done-desc');
            if (doneDesc) {
              doneDesc.textContent = result.message || '商品信息已导入 AI店长，AI 正在生成上架内容。';
            }
            showBtn('aidz-lp-goto', true);
            showBtn('aidz-lp-confirm', false);
            setStatus('✅ 导入成功', 'success');
          } else if (status === 'failed' || status === 'error') {
            setStatus('❌ 处理失败：' + (result.error || result.message || '未知错误'), 'error');
            showBtn('aidz-lp-goto', true);
            showBtn('aidz-lp-retry', true);
          } else {
            // 仍在处理中
            if (progressMsg) {
              progressMsg.textContent = result.message || 'AI 正在分析商品信息并生成上架内容…';
            }
            _pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
          }
        }
      );
    }

    poll();
  }

  /* ═══════════════════ 保存导入记录 ═══════════════════ */
  function _saveImportRecord(record) {
    try {
      chrome.storage.local.get(['listingImports'], (data) => {
        const imports = data.listingImports || [];
        imports.unshift(record);
        // 只保留最近 50 条
        chrome.storage.local.set({ listingImports: imports.slice(0, 50) });
      });
    } catch (_) { /* 非关键操作，静默失败 */ }
  }

  /* ═══════════════════ 主逻辑 ═══════════════════ */
  let _rawData = null;
  let _chatBase = 'http://192.144.227.205:8000';

  function init() {
    const { fab, panel } = buildPanel();

    // 关闭按钮
    document.getElementById('aidz-lp-close').addEventListener('click', () => {
      panel.classList.remove('open');
      _pollTimer && clearTimeout(_pollTimer);
    });

    // 重新提取
    document.getElementById('aidz-lp-retry').addEventListener('click', () => {
      openPanel();
    });

    // 前往管理后台
    document.getElementById('aidz-lp-goto').addEventListener('click', () => {
      chrome.storage.sync.get(['chatApiBase'], (s) => {
        const base = s.chatApiBase || _chatBase;
        window.open(base.replace(':8000', '') + '/admin/listings', '_blank');
      });
    });

    // 确认导入按钮
    document.getElementById('aidz-lp-confirm').addEventListener('click', () => {
      const formData = collectFormData(_rawData);
      if (!formData.title) {
        setStatus('请填写商品标题后再导入', 'error');
        return;
      }

      showBtn('aidz-lp-confirm', false);
      setStatus('正在提交…');
      showView('aidz-lp-view-progress');

      chrome.runtime.sendMessage(
        { type: 'LISTING_IMPORT', payload: formData },
        (result) => {
          if (chrome.runtime.lastError) {
            showView('aidz-lp-view-error');
            document.getElementById('aidz-lp-error-msg').textContent =
              '插件通信失败，请刷新页面重试。';
            showBtn('aidz-lp-confirm', true);
            setStatus('');
            return;
          }
          if (!result?.success) {
            showView('aidz-lp-view-error');
            document.getElementById('aidz-lp-error-msg').textContent =
              '提交失败：' + (result?.error || '未知错误');
            showBtn('aidz-lp-confirm', true);
            setStatus('');
            return;
          }

          const taskId = result.taskId;
          if (taskId) {
            chrome.storage.sync.get(['chatApiBase'], (s) => {
              _chatBase = s.chatApiBase || _chatBase;
              startPolling(taskId, _chatBase);
            });
          } else {
            // 无 taskId，认为同步成功
            _saveImportRecord({
              title: formData.title,
              platform: PLATFORM,
              status: 'completed',
              taskId: null,
              url: window.location.href,
              time: Date.now(),
            });
            showView('aidz-lp-view-done');
            showBtn('aidz-lp-goto', true);
            setStatus('✅ 导入成功', 'success');
          }
        }
      );
    });

    // 悬浮按钮点击
    fab.addEventListener('click', openPanel);
  }

  function openPanel() {
    const panel = document.getElementById('aidz-listing-panel');
    if (!panel) return;

    _pollTimer && clearTimeout(_pollTimer);

    // 重置 UI
    showView('aidz-lp-view-loading');
    showBtn('aidz-lp-confirm', false);
    showBtn('aidz-lp-goto', false);
    showBtn('aidz-lp-retry', false);
    setStatus('');
    panel.classList.add('open');

    // 提取数据（给页面一点时间渲染）
    setTimeout(() => {
      _rawData = extractProductData();

      if (!_rawData || !_rawData.title) {
        // 提取失败但仍显示表单让用户手动填
        _rawData = _rawData || {
          source_platform: PLATFORM,
          source_url: window.location.href,
          title: '', price: '', images: [], specs: {},
          brand: '', barcode: '', min_order: '', shop_name: '',
          description: '', registration_cert: '', device_class: '',
        };

        showView('aidz-lp-view-error');
        // 同时让错误视图和表单视图都可见，方便手动填写
        const formView = document.getElementById('aidz-lp-view-form');
        if (formView) formView.classList.add('active');

        fillForm(_rawData);
        showBtn('aidz-lp-confirm', true);
        setStatus('部分信息未能自动提取，请手动补充', 'error');
      } else {
        fillForm(_rawData);
        showView('aidz-lp-view-form');
        showBtn('aidz-lp-confirm', true);

        const missingFields = [];
        if (!_rawData.title) missingFields.push('标题');
        if (!_rawData.price) missingFields.push('价格');
        if (!_rawData.images?.length) missingFields.push('图片');

        if (missingFields.length > 0) {
          setStatus(`⚠️ 未能提取：${missingFields.join('、')}，请手动补充`);
        } else {
          setStatus('✅ 商品信息提取完成，请确认后导入');
        }
      }
    }, 500);
  }

  /* ═══════════════════ 启动 ═══════════════════ */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
