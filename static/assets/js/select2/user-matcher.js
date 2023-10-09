/**
 * 用于select2的用户搜索函数，适用于由统一导出搜索索引函数生成的搜索索引。
 * @module select2/user-matcher
 */

/**
 * @typedef {object} Params - 用于搜索的参数对象
 * @property {string} term - 用户输入的搜索词。
 */

/**
 * @typedef {object} SearchData - 用于搜索的数据对象
 * @property {string} text - 在下拉列表中显示的文本
 * @property {string} [pinyin] - 文本的拼音。
 * @property {string} [acronym] - 文本的首字母缩写
 */

/**
 * 用于搜索用户的自定义搜索函数
 * @param {Params} params - 包含搜索参数的对象。
 * @param {SearchData} data - 包含要判断的数据对象。
 * @returns {?SearchData} 该数据对象的搜索结果，如果不符合搜索条件，则返回 null。
 */
function matchUser(params, data) {
    // 如果没有搜索条件，则返回所有数据
    if ($.trim(params.term) === '') {
        return data;
    }
    // 如果没有'text'属性，则不显示该项
    if (typeof data.text === 'undefined') {
        return null;
    }
    // `params.term` 是搜索关键词
    // `data.text` 是显示数据对象的文本
    // 可用 `$.extend(true, {}, data);` 深拷贝并返回修改对象
    if (data.text.indexOf(params.term) > -1) { return data; }
    if (data.pinyin && data.pinyin.indexOf(params.term) > -1) {
        return data;
    }
    if (data.acronym && data.acronym.indexOf(params.term) > -1 ){
        return data;
    }
    // 不显示该搜索结果
    return null;
}
