// 第 130 轮：数字工厂的中英切换（细则 D-1、D-2）。
// t('中文原文', { 变量 }) —— 中文原文就是钥匙，英文在 locales/en.json；缺英文就显示中文。
// 语言：用户点过“中文/EN”的以点过的为准（存在浏览器里）；没点过按站点：国内站 wenquestech.online 中文，其余英文。
import { reactive } from 'vue';
import en from '../locales/en.json';
import phraseList from '../locales/en_phrases.json';
import nameList from '../locales/en_names.json';
import tplList from '../locales/en_templates.json';     // 第三批：后端写的句子（句型）      // 第二批：各厂清单里的名字（tools/plant_names.py 生成）
import { compileTemplates, enPart, fill, hasCjk, siteLang, sortPhrases, translate } from './i18n-core.js';

const KEY = 'wq-factory-lang';
const PHRASES = sortPhrases([...phraseList, ...nameList]);
const TPLS = compileTemplates(tplList);

function stored() {
  try { const v = localStorage.getItem(KEY); return v === 'zh' || v === 'en' ? v : null; } catch (e) { return null; }
}

export const i18n = reactive({ lang: stored() || siteLang(typeof location !== 'undefined' ? location.hostname : '') });

function apply() {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = i18n.lang === 'en' ? 'en' : 'zh-CN';
  document.title = i18n.lang === 'en' ? 'WenQuest Digital Factory' : '问渠数字工厂';
  // 枢纽按这个返回提示的语言（网页的请求另带 x-wq-lang 头；直接 fetch 的文件、下载走 cookie）
  try { document.cookie = 'wq_lang=' + i18n.lang + '; path=/; max-age=31536000; SameSite=Lax'; } catch (e) { /* 不让写 cookie */ }
}
apply();

export function setLang(l) {
  i18n.lang = l === 'zh' ? 'zh' : 'en';
  try { localStorage.setItem(KEY, i18n.lang); } catch (e) { /* 无痕窗口：只在这一页有效 */ }
  apply();
}

export const isEn = () => i18n.lang === 'en';
// 数字、日期的格式按语言
export const loc = () => (i18n.lang === 'en' ? 'en-US' : 'zh-CN');

// 页面上的固定文字
// 同一中文在不同地方英文不同时，钥匙写成“中文|用处”（如 '运行|按钮'），中文界面只显示“|”前面
export function t(zh, vars) {
  const base = zh && zh.includes('|') ? zh.slice(0, zh.indexOf('|')) : zh;
  return fill(i18n.lang === 'en' ? (en[zh] || base) : base, vars);
}
// 只是标出“这是要翻译的文字”（写在数据表里），显示时再 t()
export const tk = (zh) => zh;
// 数据里的文字（设计产物、仿真结果、测试程序……）：先查表，查不到按词组表换，换不干净就显示中文
export function td(zh) {
  if (i18n.lang !== 'en' || zh == null) return zh ?? '';
  return translate(zh, en, PHRASES, TPLS);
}
// 对象的名字：英文时取 <字段>_en（工厂清单的 name_en 等），没有就取中英合写名字的英文部分，再没有就中文
export function nm(o, f = 'name') {
  if (!o) return '';
  const zh = o[f];
  if (i18n.lang !== 'en') return zh ?? '';
  return o[f + '_en'] || bi(zh);
}
// 中英合写的一个字符串（“示例·传感器厂 Sensor Maker (Demo)”）：英文时取英文部分
export function bi(s) {
  if (i18n.lang !== 'en' || !hasCjk(s)) return s ?? '';
  return enPart(s) || td(s);
}
// { zh, en } 对象（零件库的数据）
export function zhen(o) {
  if (o == null) return '';
  if (typeof o === 'string') return i18n.lang === 'en' ? td(o) : o;
  return (i18n.lang === 'en' ? o.en || td(o.zh) : o.zh || o.en) || '';
}
