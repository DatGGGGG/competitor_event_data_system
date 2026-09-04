/**
 * event_api_client_v2.gs
 *
 * Complete replacement for the Event API Apps Script client.
 *
 * Required existing Apps Script dependencies:
 * - CONFIG.APP_LIST_SHEET and CONFIG.DATA_SHEET (optional; defaults below apply)
 * - CONFIG_2.BIWEEKLY_SUMMARY.STATS for EVENTS | BIWEEKLY and EVENTS | ALL
 * - isEnabled_ (optional; enabled values are accepted when unavailable)
 * - getSheetDisplayRows_ for the reporting sheet source
 * - formatMetricNumber_ (optional; a plain numeric fallback is used)
 *
 * Required Script Properties:
 * - MARKET_RESEARCH_API_BASE_URL=https://market-data.garena.vn
 * - MARKET_RESEARCH_EVENT_API_KEY=<issued Event API key>
 */

const EVENT_REPORT_CONFIG = {
  APP_LIST_SHEET_FALLBACK: 'APP_LIST',
  DATA_SHEET_FALLBACK: 'RAW DATA | ALL',
  SCRIPT_PROP_BASE_URL: 'MARKET_RESEARCH_API_BASE_URL',
  SCRIPT_PROP_API_KEY: 'MARKET_RESEARCH_EVENT_API_KEY',
  DEFAULT_PUBLIC_BASE_URL: 'https://market-data.garena.vn',
  TOP_EVENT_COUNT: 3,
  HAS_FB_POSTS_ONLY: true,
  MIN_SOCIAL_SCORE: '',
  DISPLAY_METRIC_FIELD: 'total_reaction_fb',
  INCLUDE_EVENT_DATE_SPAN: false,
  NO_EVENT_TEXT: '',
  REQUEST_RETRY_LIMIT: 4,
  RETRYABLE_STATUS_CODES: [429, 500, 502, 503, 504],
  GAME_NAME_ALIASES: {}
};

var EVENT_API_CACHE_ = {};
var UNIFIED_APP_LOOKUP_CACHE_ = null;

const EVENT_CATEGORY_LABELS = {
  patch_release: 'patch',
  feature_update: 'feature',
  game_mode_launch: 'mode',
  new_hero_release: 'new hero',
  hero_revamp: 'revamp',
  skin_release: 'new skin',
  season_launch: 'season',
  in_game_event: 'live event',
  store_promotion: 'promo',
  ip_collaboration: 'IP collab',
  other_collaboration: 'brand collab',
  ugc: 'UGC',
  offline_event: 'offline',
  esports: 'esports',
  other: 'other'
};

var REPORT_EVENTS_SHEET_CONFIG = {
  SHEET_NAME: 'EVENTS | BIWEEKLY',
  HAS_FB_POSTS_ONLY: false,
  MIN_SOCIAL_SCORE: '',
  RETRY_LIMIT: 4,
  RETRYABLE_STATUS_CODES: [429, 500, 502, 503, 504]
};

var REPORT_EVENTS_HEADERS = [
  'refresh_date', 'month_bucket_loaded', 'time_range_start', 'time_range_end',
  'unified_app_id', 'game_name',
  'unified_event_id', 'event_name', 'event_category', 'event_category_label',
  'estimated_start_date', 'estimated_end_date', 'month_bucket',
  'anchor_source_type', 'merge_confidence',
  'fb_post_count', 'st_app_update_event_count', 'st_version_event_count',
  'total_engagement_fb', 'total_reaction_fb', 'total_comment_fb',
  'total_share_fb', 'total_view_fb', 'social_score',
  'event_description', 'top_post_link'
];

var EVENT_BACKFILL_CONFIG = {
  SHEET_NAME: 'EVENTS | ALL',
  START_MONTH: '2026-01',
  CURSOR_PROP: 'EVENTS_BACKFILL_CURSOR_MONTH',
  HANDLER_FUNCTION: 'backfillEventsOneMonth'
};

function setMarketResearchApiBaseUrl(baseUrl) {
  const cleanBaseUrl = String(baseUrl || '').trim().replace(/\/+$/, '');
  if (!cleanBaseUrl) throw new Error('Base URL is empty.');

  PropertiesService.getScriptProperties().setProperty(
    EVENT_REPORT_CONFIG.SCRIPT_PROP_BASE_URL,
    cleanBaseUrl
  );
  Logger.log('Set Event API base URL = ' + cleanBaseUrl);
}

function setEventLookupApiBaseUrl(baseUrl) {
  setMarketResearchApiBaseUrl(baseUrl);
}

function setEventLookupApiBaseUrlPublic() {
  setMarketResearchApiBaseUrl('https://market-data.garena.vn');
}

function eventApiConfig_() {
  const props = PropertiesService.getScriptProperties();
  const baseUrl = String(
    props.getProperty(EVENT_REPORT_CONFIG.SCRIPT_PROP_BASE_URL) ||
    EVENT_REPORT_CONFIG.DEFAULT_PUBLIC_BASE_URL
  ).trim().replace(/\/+$/, '');
  const apiKey = String(
    props.getProperty(EVENT_REPORT_CONFIG.SCRIPT_PROP_API_KEY) || ''
  ).trim();

  if (!apiKey) {
    throw new Error(
      'Missing Script Property: ' + EVENT_REPORT_CONFIG.SCRIPT_PROP_API_KEY +
      '. Add the issued Event API key in Project Settings > Script properties.'
    );
  }

  return { baseUrl: baseUrl, apiKey: apiKey };
}

function encodeEventApiQuery_(params) {
  const parts = [];
  Object.keys(params || {}).forEach(function(key) {
    const value = params[key];
    if (value === null || value === undefined || value === '') return;

    if (Array.isArray(value)) {
      value.forEach(function(item) {
        if (item === null || item === undefined || item === '') return;
        parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(item)));
      });
      return;
    }
    parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(value)));
  });
  return parts.join('&');
}

function eventApiFetch_(path, queryParams) {
  const config = eventApiConfig_();
  const query = encodeEventApiQuery_(queryParams || {});
  const url = query ? config.baseUrl + path + '?' + query : config.baseUrl + path;
  let lastError = null;

  for (let attempt = 1; attempt <= EVENT_REPORT_CONFIG.REQUEST_RETRY_LIMIT; attempt++) {
    const response = UrlFetchApp.fetch(url, {
      method: 'get',
      headers: { 'X-API-Key': config.apiKey },
      muteHttpExceptions: true
    });
    const status = response.getResponseCode();
    const bodyText = response.getContentText();
    let payload;

    try {
      payload = bodyText ? JSON.parse(bodyText) : {};
    } catch (error) {
      throw new Error(
        'Event API returned non-JSON response (' + status + ') on ' + path + ': ' +
        bodyText.slice(0, 1000)
      );
    }

    if (status === 200) return payload;

    const detail = payload && (payload.detail || payload.error);
    const message = typeof detail === 'string'
      ? detail
      : JSON.stringify(detail || bodyText.slice(0, 1000));
    lastError = new Error(
      'Event API request failed (' + status + ') on ' + path + ': ' + message
    );

    if (
      attempt < EVENT_REPORT_CONFIG.REQUEST_RETRY_LIMIT &&
      EVENT_REPORT_CONFIG.RETRYABLE_STATUS_CODES.indexOf(status) >= 0
    ) {
      Utilities.sleep(Math.min(8000, Math.pow(2, attempt - 1) * 1000));
      continue;
    }
    break;
  }
  throw lastError || new Error('Event API request failed on ' + path);
}

/* Compatibility names used by older report functions. */
function marketResearchApiFetch_(path, queryParams) {
  return eventApiFetch_(path, queryParams);
}

function eventLookupApiFetch_(path, queryParams) {
  return eventApiFetch_(path, queryParams);
}

function normalizeGameKey_(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '');
}

function getEventCategoryDisplayLabel_(category) {
  const key = String(category || '').trim();
  return EVENT_CATEGORY_LABELS[key] || key || '';
}

function getAppListSheetName_() {
  return typeof CONFIG !== 'undefined' && CONFIG && CONFIG.APP_LIST_SHEET
    ? CONFIG.APP_LIST_SHEET
    : EVENT_REPORT_CONFIG.APP_LIST_SHEET_FALLBACK;
}

function getDataSheetName_() {
  return typeof CONFIG !== 'undefined' && CONFIG && CONFIG.DATA_SHEET
    ? CONFIG.DATA_SHEET
    : EVENT_REPORT_CONFIG.DATA_SHEET_FALLBACK;
}

function addGameNameLookup_(lookup, gameName, unifiedAppId) {
  const cleanName = String(gameName || '').trim();
  const cleanId = String(unifiedAppId || '').trim();
  if (!cleanName || !cleanId) return;
  if (!lookup[cleanName]) lookup[cleanName] = cleanId;
  const normalized = normalizeGameKey_(cleanName);
  if (!lookup[normalized]) lookup[normalized] = cleanId;
}

function buildEnabledUnifiedAppIdSet_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(getAppListSheetName_());
  if (!sheet) throw new Error('Sheet not found: ' + getAppListSheetName_());
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return {};

  const headers = values[0].map(String);
  const idIndex = headers.indexOf('unified_app_id');
  const enabledIndex = headers.indexOf('enabled');
  if (idIndex === -1) throw new Error(getAppListSheetName_() + ' must contain unified_app_id.');

  const enabled = {};
  values.slice(1).forEach(function(row) {
    const appId = String(row[idIndex] || '').trim();
    const enabledValue = enabledIndex >= 0 ? row[enabledIndex] : true;
    if (!appId) return;
    if (typeof isEnabled_ === 'function' && !isEnabled_(enabledValue)) return;
    enabled[appId] = true;
  });
  return enabled;
}

function buildUnifiedAppIdLookupFromDataSheet_(enabledIds) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(getDataSheetName_());
  if (!sheet) throw new Error('Sheet not found: ' + getDataSheetName_());
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return {};

  const headers = values[0].map(String);
  const idIndex = headers.indexOf('unified_app_id');
  const gameIndex = headers.indexOf('game_name');
  if (idIndex === -1 || gameIndex === -1) {
    throw new Error(getDataSheetName_() + ' must contain unified_app_id and game_name.');
  }

  const lookup = {};
  values.slice(1).forEach(function(row) {
    const appId = String(row[idIndex] || '').trim();
    const gameName = String(row[gameIndex] || '').trim();
    if (!appId || !gameName || !enabledIds[appId]) return;
    addGameNameLookup_(lookup, gameName, appId);
  });
  return lookup;
}

function buildUnifiedAppIdLookup_() {
  if (UNIFIED_APP_LOOKUP_CACHE_) return UNIFIED_APP_LOOKUP_CACHE_;
  const lookup = buildUnifiedAppIdLookupFromDataSheet_(buildEnabledUnifiedAppIdSet_());

  Object.keys(EVENT_REPORT_CONFIG.GAME_NAME_ALIASES).forEach(function(alias) {
    const target = EVENT_REPORT_CONFIG.GAME_NAME_ALIASES[alias];
    const appId = lookup[target] || lookup[normalizeGameKey_(target)];
    if (!appId) return;
    addGameNameLookup_(lookup, alias, appId);
  });

  UNIFIED_APP_LOOKUP_CACHE_ = lookup;
  return lookup;
}

function getUnifiedAppIdForGameName_(gameName) {
  const lookup = buildUnifiedAppIdLookup_();
  return lookup[gameName] || lookup[normalizeGameKey_(gameName)] || '';
}

function resetOutstandingEventCaches_() {
  EVENT_API_CACHE_ = {};
  UNIFIED_APP_LOOKUP_CACHE_ = null;
}

function parseReportDate_(value) {
  if (Object.prototype.toString.call(value) === '[object Date]' && !isNaN(value.getTime())) {
    return new Date(value.getFullYear(), value.getMonth(), value.getDate());
  }
  const text = String(value || '').trim();
  let match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (match) return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (match) return new Date(Number(match[3]), Number(match[1]) - 1, Number(match[2]));
  const parsed = new Date(text);
  if (!isNaN(parsed.getTime())) {
    return new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  }
  throw new Error('Unsupported report date format: ' + text);
}

function addDaysReport_(dateObj, days) {
  const date = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
  date.setDate(date.getDate() + days);
  return date;
}

function formatDateIso_(dateObj) {
  return dateObj.getFullYear() + '-' +
    String(dateObj.getMonth() + 1).padStart(2, '0') + '-' +
    String(dateObj.getDate()).padStart(2, '0');
}

function getBiweeklyEventWindow_(reportDateValue) {
  const endDate = parseReportDate_(reportDateValue);
  return {
    startDate: formatDateIso_(addDaysReport_(endDate, -13)),
    endDate: formatDateIso_(endDate)
  };
}

/* v2 events are scoped by event month_bucket, never raw post publish date. */
function eventMonthScopeFromDates_(startDate, endDate) {
  const start = String(startDate || '').trim();
  const end = String(endDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) {
    throw new Error('Expected YYYY-MM-DD start/end dates.');
  }
  return { start_month: start.slice(0, 7), end_month: end.slice(0, 7) };
}

function eventParams_(startDate, endDate, top, hasFbPosts, minSocialScore) {
  const scope = eventMonthScopeFromDates_(startDate, endDate);
  const params = { start_month: scope.start_month, end_month: scope.end_month };
  if (top) params.top = top;
  if (hasFbPosts === true) params.has_fb_posts = 'true';
  if (minSocialScore !== null && minSocialScore !== undefined && minSocialScore !== '') {
    params.min_social_score = minSocialScore;
  }
  return params;
}

function fetchGameEventsV2_(unifiedAppId, params) {
  return eventApiFetch_(
    '/api/events/v2/games/' + encodeURIComponent(unifiedAppId) + '/events',
    params
  );
}

function extractEventRowsFromApiPayload_(payload) {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload.results)) return payload.results;
  return [];
}

function safeEventNumber_(value) {
  const number = Number(value);
  return isNaN(number) ? 0 : number;
}

function normalizeApiEventRow_(item) {
  item = item || {};
  return {
    unified_event_id: item.unified_event_id || '',
    event_name: item.canonical_event_name || item.event_name || '',
    event_category: item.event_category || '',
    estimated_start_date: item.estimated_start_date || '',
    estimated_end_date: item.estimated_end_date || '',
    event_description: item.canonical_event_description || item.event_description || '',
    anchor_source_type: item.anchor_source_type || '',
    merge_confidence: item.merge_confidence || '',
    month_bucket: item.month_bucket || '',
    fb_post_count: safeEventNumber_(item.fb_post_count),
    st_app_update_event_count: safeEventNumber_(item.st_app_update_event_count),
    st_version_event_count: safeEventNumber_(item.st_version_event_count),
    total_engagement_fb: safeEventNumber_(item.total_engagement_fb),
    total_reaction_fb: safeEventNumber_(item.total_reaction_fb),
    total_comment_fb: safeEventNumber_(item.total_comment_fb),
    total_share_fb: safeEventNumber_(item.total_share_fb),
    total_view_fb: safeEventNumber_(item.total_view_fb),
    social_score: safeEventNumber_(item.social_score)
  };
}

function normalizeEventLookupRow_(item) {
  return normalizeApiEventRow_(item);
}

function fetchOutstandingEventsForGame_(gameName, reportDateValue) {
  const appId = getUnifiedAppIdForGameName_(gameName);
  if (!appId) {
    Logger.log('No unified_app_id mapping found for game: ' + gameName);
    return [];
  }
  const window = getBiweeklyEventWindow_(reportDateValue);
  const cacheKey = ['outstanding', appId, window.startDate, window.endDate].join('|');
  if (EVENT_API_CACHE_[cacheKey]) return EVENT_API_CACHE_[cacheKey];

  const payload = fetchGameEventsV2_(appId, eventParams_(
    window.startDate,
    window.endDate,
    EVENT_REPORT_CONFIG.TOP_EVENT_COUNT,
    EVENT_REPORT_CONFIG.HAS_FB_POSTS_ONLY,
    EVENT_REPORT_CONFIG.MIN_SOCIAL_SCORE
  ));

  const events = extractEventRowsFromApiPayload_(payload)
    .map(normalizeApiEventRow_)
    .filter(function(item) { return String(item.event_name || '').trim() !== ''; })
    .sort(function(a, b) {
      return Number(b.social_score) - Number(a.social_score) ||
        Number(b.total_engagement_fb) - Number(a.total_engagement_fb) ||
        String(a.event_name).localeCompare(String(b.event_name));
    })
    .slice(0, EVENT_REPORT_CONFIG.TOP_EVENT_COUNT);

  EVENT_API_CACHE_[cacheKey] = events;
  return events;
}

function getEventsForGame(gameName, reportDateValue) {
  const events = fetchOutstandingEventsForGame_(gameName, reportDateValue);
  Logger.log(JSON.stringify(events, null, 2));
  return events;
}

function getEventsByUnifiedAppId(unifiedAppId, startDate, endDate) {
  return fetchGameEventsV2_(unifiedAppId, eventParams_(
    startDate,
    endDate,
    EVENT_REPORT_CONFIG.TOP_EVENT_COUNT,
    EVENT_REPORT_CONFIG.HAS_FB_POSTS_ONLY,
    EVENT_REPORT_CONFIG.MIN_SOCIAL_SCORE
  ));
}

function getEventDisplayMetricValue_(eventItem) {
  return Number(eventItem[EVENT_REPORT_CONFIG.DISPLAY_METRIC_FIELD] || 0);
}

function formatMonthDayFromIsoLike_(value) {
  const match = String(value || '').trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return '';
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return names[Number(match[2]) - 1] + ' ' + Number(match[3]);
}

function formatEventDateSpanForDisplay_(startValue, endValue) {
  const start = formatMonthDayFromIsoLike_(startValue);
  const end = formatMonthDayFromIsoLike_(endValue);
  if (start && end) return start === end ? start : start + ' - ' + end;
  return start || end || '';
}

function formatOutstandingEventsText_(events) {
  if (!events || !events.length) return EVENT_REPORT_CONFIG.NO_EVENT_TEXT;
  const formatter = typeof formatMetricNumber_ === 'function'
    ? formatMetricNumber_
    : function(value) { return String(value); };

  return events.map(function(item) {
    const category = getEventCategoryDisplayLabel_(item.event_category);
    const span = formatEventDateSpanForDisplay_(item.estimated_start_date, item.estimated_end_date);
    const suffix = EVENT_REPORT_CONFIG.INCLUDE_EVENT_DATE_SPAN && span ? ' [' + span + ']' : '';
    return item.event_name + (category ? ' ' + category : '') + suffix +
      ' (' + formatter(getEventDisplayMetricValue_(item)) + ')';
  }).join('; ');
}

function buildOutstandingEventsLineForGame_(gameName, reportDateValue) {
  return formatOutstandingEventsText_(fetchOutstandingEventsForGame_(gameName, reportDateValue));
}

function testEventsApiConnection() {
  const payload = eventApiFetch_(
    '/api/events/v2/games/57955d280211a6718a000002/events',
    { month: '2026-06', top: 3, has_fb_posts: 'true' }
  );
  Logger.log(JSON.stringify(payload, null, 2));
  return payload;
}

function previewOutstandingEventsForMlbb() {
  const events = fetchOutstandingEventsForGame_('Mobile Legends: Bang Bang', '2026-06-07');
  Logger.log(JSON.stringify(events, null, 2));
  Logger.log(formatOutstandingEventsText_(events));
  return events;
}

function debugEnabledUnifiedAppIds_() {
  Logger.log(JSON.stringify(buildEnabledUnifiedAppIdSet_(), null, 2));
}

function debugUnifiedAppLookup_() {
  resetOutstandingEventCaches_();
  Logger.log(JSON.stringify(buildUnifiedAppIdLookup_(), null, 2));
}

function getOrCreateReportEventsSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(REPORT_EVENTS_SHEET_CONFIG.SHEET_NAME) ||
    ss.insertSheet(REPORT_EVENTS_SHEET_CONFIG.SHEET_NAME);
}

function todayEventLocal_() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function getCurrentMonthEventWindow_() {
  const today = todayEventLocal_();
  const start = new Date(today.getFullYear(), today.getMonth(), 1);
  const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  return {
    refreshDate: formatDateIso_(today),
    monthBucket: formatMonthString_(start),
    startDate: formatDateIso_(start),
    endDate: formatDateIso_(end)
  };
}

function getCurrentBiweeklyReportGamesForEvents_() {
  if (typeof CONFIG_2 === 'undefined' || !CONFIG_2.BIWEEKLY_SUMMARY) {
    throw new Error('CONFIG_2.BIWEEKLY_SUMMARY is not available.');
  }
  if (typeof getSheetDisplayRows_ !== 'function') {
    throw new Error('Missing helper: getSheetDisplayRows_.');
  }

  const config = CONFIG_2.BIWEEKLY_SUMMARY.STATS;
  const seen = {};
  const games = [];
  getSheetDisplayRows_(config.SHEET_NAME).forEach(function(row) {
    const gameName = String(row[config.COL_GAME_NAME - 1] || '').trim();
    if (!gameName || gameName.toLowerCase() === 'game_name' || seen[gameName]) return;
    seen[gameName] = true;
    const appId = getUnifiedAppIdForGameName_(gameName);
    if (!appId) {
      Logger.log('No unified_app_id mapping found for game: ' + gameName);
      return;
    }
    games.push({ gameName: gameName, unifiedAppId: appId });
  });

  if (!games.length) throw new Error('No valid mapped games found in ' + config.SHEET_NAME);
  const window = getCurrentMonthEventWindow_();
  return { reportDateValue: window.refreshDate, monthBucket: window.monthBucket, window: window, games: games };
}

function fetchAllEventsForReportGame_(game, window) {
  const payload = fetchGameEventsV2_(game.unifiedAppId, eventParams_(
    window.startDate,
    window.endDate,
    null,
    REPORT_EVENTS_SHEET_CONFIG.HAS_FB_POSTS_ONLY,
    REPORT_EVENTS_SHEET_CONFIG.MIN_SOCIAL_SCORE
  ));
  return extractEventRowsFromApiPayload_(payload)
    .map(normalizeEventLookupRow_)
    .filter(function(item) { return String(item.event_name || '').trim() !== ''; })
    .sort(function(a, b) {
      return String(a.estimated_start_date).localeCompare(String(b.estimated_start_date)) ||
        String(a.month_bucket).localeCompare(String(b.month_bucket)) ||
        String(a.event_name).localeCompare(String(b.event_name));
    });
}

function fetchTopPostLinkForEvent_(unifiedEventId, fbPostCount) {
  const eventId = String(unifiedEventId || '').trim();
  if (!eventId || Number(fbPostCount || 0) <= 0) return '';
  const cacheKey = 'top_post_link|' + eventId;
  if (EVENT_API_CACHE_[cacheKey] !== undefined) return EVENT_API_CACHE_[cacheKey];

  try {
    const linkedPosts = eventApiFetch_(
      '/api/events/v2/events/' + encodeURIComponent(eventId) + '/posts',
      {}
    );
    const posts = linkedPosts && linkedPosts.result && Array.isArray(linkedPosts.result.posts)
      ? linkedPosts.result.posts.slice()
      : [];
    posts.sort(function(a, b) { return Number(b.social_score || 0) - Number(a.social_score || 0); });
    const sourcePostId = posts.length ? String(posts[0].source_post_id || '').trim() : '';
    if (!sourcePostId) return '';

    const detail = eventApiFetch_(
      '/api/events/v2/posts/' + encodeURIComponent(sourcePostId),
      {}
    );
    const link = detail && detail.result && detail.result.link ? String(detail.result.link).trim() : '';
    EVENT_API_CACHE_[cacheKey] = link;
    return link;
  } catch (error) {
    Logger.log('Top post link lookup failed for event ' + eventId + ': ' + error);
    EVENT_API_CACHE_[cacheKey] = '';
    return '';
  }
}

function eventSheetRow_(refreshDate, window, game, item, topPostLink) {
  const categoryLabel = getEventCategoryDisplayLabel_(item.event_category);
  return [
    refreshDate, window.monthBucket, window.startDate, window.endDate,
    game.unifiedAppId, game.gameName,
    item.unified_event_id, item.event_name, item.event_category, categoryLabel,
    item.estimated_start_date, item.estimated_end_date, item.month_bucket,
    item.anchor_source_type, item.merge_confidence,
    item.fb_post_count, item.st_app_update_event_count, item.st_version_event_count,
    item.total_engagement_fb, item.total_reaction_fb, item.total_comment_fb,
    item.total_share_fb, item.total_view_fb, item.social_score,
    item.event_description, topPostLink
  ];
}

function buildReportEventsSheetRows_() {
  const source = getCurrentBiweeklyReportGamesForEvents_();
  const rows = [];
  source.games.forEach(function(game) {
    try {
      fetchAllEventsForReportGame_(game, source.window).forEach(function(item) {
        rows.push(eventSheetRow_(
          source.reportDateValue,
          source.window,
          game,
          item,
          fetchTopPostLinkForEvent_(item.unified_event_id, item.fb_post_count)
        ));
      });
    } catch (error) {
      Logger.log('Event fetch failed for ' + game.gameName + ': ' + error);
    }
  });
  return { reportDateValue: source.reportDateValue, window: source.window, games: source.games, rows: rows };
}

function refreshReportEventsSheet() {
  const result = buildReportEventsSheetRows_();
  const sheet = getOrCreateReportEventsSheet_();
  sheet.clearContents();
  sheet.getRange(1, 1, 1, REPORT_EVENTS_HEADERS.length).setValues([REPORT_EVENTS_HEADERS]);
  if (result.rows.length) {
    sheet.getRange(2, 1, result.rows.length, REPORT_EVENTS_HEADERS.length).setValues(result.rows);
  }
  sheet.setFrozenRows(1);
  SpreadsheetApp.flush();
  Logger.log('Refreshed ' + REPORT_EVENTS_SHEET_CONFIG.SHEET_NAME + ': ' + result.rows.length + ' events.');
  return { sheet_name: REPORT_EVENTS_SHEET_CONFIG.SHEET_NAME, event_count: result.rows.length };
}

function debugOneEventsApiResponse() {
  const source = getCurrentBiweeklyReportGamesForEvents_();
  if (!source.games.length) return null;
  const game = source.games[0];
  const payload = fetchGameEventsV2_(game.unifiedAppId, eventParams_(
    source.window.startDate,
    source.window.endDate,
    null,
    REPORT_EVENTS_SHEET_CONFIG.HAS_FB_POSTS_ONLY,
    REPORT_EVENTS_SHEET_CONFIG.MIN_SOCIAL_SCORE
  ));
  Logger.log(JSON.stringify(payload, null, 2).slice(0, 5000));
  return payload;
}

function previewReportEventsSheetBuild() {
  const result = buildReportEventsSheetRows_();
  Logger.log(JSON.stringify(result.rows.slice(0, 5), null, 2));
  return result.rows.slice(0, 5);
}

function parseMonthString_(monthStr) {
  const match = String(monthStr || '').trim().match(/^(\d{4})-(\d{2})$/);
  if (!match) throw new Error('Invalid month string: ' + monthStr + '. Expected YYYY-MM.');
  return new Date(Number(match[1]), Number(match[2]) - 1, 1);
}

function formatMonthString_(dateObj) {
  return dateObj.getFullYear() + '-' + String(dateObj.getMonth() + 1).padStart(2, '0');
}

function addMonths_(dateObj, months) {
  return new Date(dateObj.getFullYear(), dateObj.getMonth() + months, 1);
}

function getMonthWindow_(monthStr) {
  const start = parseMonthString_(monthStr);
  const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  return { monthBucket: formatMonthString_(start), startDate: formatDateIso_(start), endDate: formatDateIso_(end) };
}

function getCurrentMonthString_() {
  return formatMonthString_(todayEventLocal_());
}

function resetEventsBackfillCursor(monthStr) {
  PropertiesService.getScriptProperties().setProperty(
    EVENT_BACKFILL_CONFIG.CURSOR_PROP,
    monthStr || EVENT_BACKFILL_CONFIG.START_MONTH
  );
}

function getEventsBackfillCursor_() {
  return PropertiesService.getScriptProperties().getProperty(EVENT_BACKFILL_CONFIG.CURSOR_PROP) ||
    EVENT_BACKFILL_CONFIG.START_MONTH;
}

function getOrCreateEventsAllSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(EVENT_BACKFILL_CONFIG.SHEET_NAME) || ss.insertSheet(EVENT_BACKFILL_CONFIG.SHEET_NAME);
}

function deleteRowBlocks_(sheet, rowNumbers) {
  if (!rowNumbers || !rowNumbers.length) return;
  rowNumbers.sort(function(a, b) { return b - a; });
  rowNumbers.forEach(function(rowNumber) { sheet.deleteRow(rowNumber); });
}

function deleteExistingEventsForMonth_(sheet, monthBucket) {
  if (sheet.getLastRow() <= 1) return;
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const monthColumn = headers.indexOf('month_bucket_loaded') + 1;
  if (!monthColumn) throw new Error('Could not find month_bucket_loaded column.');
  const values = sheet.getRange(2, monthColumn, sheet.getLastRow() - 1, 1).getDisplayValues();
  const rows = [];
  values.forEach(function(row, index) {
    if (String(row[0] || '').trim() === monthBucket) rows.push(index + 2);
  });
  deleteRowBlocks_(sheet, rows);
}

function buildEventRowsForMonth_(monthStr) {
  const window = getMonthWindow_(monthStr);
  const source = getCurrentBiweeklyReportGamesForEvents_();
  const rows = [];
  source.games.forEach(function(game) {
    try {
      fetchAllEventsForReportGame_(game, window).forEach(function(item) {
        rows.push(eventSheetRow_(
          formatDateIso_(todayEventLocal_()), window, game, item,
          fetchTopPostLinkForEvent_(item.unified_event_id, item.fb_post_count)
        ));
      });
    } catch (error) {
      Logger.log('Event fetch failed for ' + game.gameName + ' in ' + monthStr + ': ' + error);
    }
  });
  return { monthBucket: window.monthBucket, startDate: window.startDate, endDate: window.endDate, games: source.games, rows: rows };
}

function backfillEventsOneMonth() {
  const cursor = getEventsBackfillCursor_();
  const current = getCurrentMonthString_();
  if (cursor > current) {
    stopEventsBackfillTrigger();
    return { done: true, cursor_month: cursor };
  }

  const result = buildEventRowsForMonth_(cursor);
  const sheet = getOrCreateEventsAllSheet_();
  sheet.getRange(1, 1, 1, REPORT_EVENTS_HEADERS.length).setValues([REPORT_EVENTS_HEADERS]);
  sheet.setFrozenRows(1);
  deleteExistingEventsForMonth_(sheet, result.monthBucket);
  if (result.rows.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, result.rows.length, REPORT_EVENTS_HEADERS.length)
      .setValues(result.rows);
  }
  SpreadsheetApp.flush();

  const next = formatMonthString_(addMonths_(parseMonthString_(cursor), 1));
  PropertiesService.getScriptProperties().setProperty(EVENT_BACKFILL_CONFIG.CURSOR_PROP, next);
  if (next > current) stopEventsBackfillTrigger();
  return { done: next > current, loaded_month: result.monthBucket, event_count: result.rows.length, next_cursor_month: next };
}

function createEventsBackfillTrigger() {
  stopEventsBackfillTrigger();
  ScriptApp.newTrigger(EVENT_BACKFILL_CONFIG.HANDLER_FUNCTION).timeBased().everyMinutes(5).create();
}

function previewEventsBackfillOneMonth() {
  const result = buildEventRowsForMonth_(getEventsBackfillCursor_());
  Logger.log(JSON.stringify({
    month_bucket: result.monthBucket,
    event_count: result.rows.length,
    sample_rows: result.rows.slice(0, 3)
  }, null, 2));
  return result.rows.slice(0, 3);
}

function resetEventsBackfillCursorToStart() {
  resetEventsBackfillCursor(EVENT_BACKFILL_CONFIG.START_MONTH);
}

function reloadEventsJune2026() {
  resetEventsBackfillCursor('2026-06');
  return backfillEventsOneMonth();
}

function reloadCurrentMonthEventsToAll() {
  resetEventsBackfillCursor(getCurrentMonthString_());
  return backfillEventsOneMonth();
}

function removeWeeklyCurrentMonthEventsTrigger() {
  removeWeeklyEventsReloadTriggers();
}

function stopEventsBackfillTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === EVENT_BACKFILL_CONFIG.HANDLER_FUNCTION) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function getPreviousMonthString_() {
  return formatMonthString_(addMonths_(parseMonthString_(getCurrentMonthString_()), -1));
}

function reloadPreviousAndCurrentMonthEventsToAll() {
  resetEventsBackfillCursor(getPreviousMonthString_());
  const previous = backfillEventsOneMonth();
  resetEventsBackfillCursor(getCurrentMonthString_());
  const current = backfillEventsOneMonth();
  return { previous_month: previous, current_month: current };
}

function removeWeeklyEventsReloadTriggers() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    const handler = trigger.getHandlerFunction();
    if (handler === 'reloadPreviousAndCurrentMonthEventsToAll' || handler === 'reloadCurrentMonthEventsToAll') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function createWeeklyPreviousAndCurrentMonthEventsTrigger() {
  removeWeeklyEventsReloadTriggers();
  ScriptApp.newTrigger('reloadPreviousAndCurrentMonthEventsToAll')
    .timeBased()
    .everyWeeks(1)
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(18)
    .nearMinute(0)
    .create();
}
