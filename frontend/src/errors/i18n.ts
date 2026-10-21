/** 故障记录页面文案。 */
export const errorsZhCN = {
  'errors.instance': '选择实例',
  'errors.title': '故障记录', 'errors.hint': '查看脚本报错时保存的日志和最近截图；刷新不会操作游戏。',
  'errors.refresh': '刷新记录', 'errors.empty': '暂无故障记录',
  'errors.emptyHint': '开启「保存错误日志」后，新错误会自动保存到这里。已归档的旧记录不在此列表中。',
  'errors.disabled': '当前未开启「保存错误日志」，新的错误不会保存现场；已有记录仍可查看。',
  'errors.count': '共 {count} 条', 'errors.screenshots': '{count} 张截图', 'errors.noLog': '此现场未保存日志',
  'errors.log': '错误日志', 'errors.images': '现场截图', 'errors.noImages': '此现场未保存截图',
  'errors.downloadLog': '下载完整日志', 'errors.downloadImage': '下载截图', 'errors.enlarge': '放大截图',
  'errors.truncated': '仅显示日志末尾 256 KiB，可下载完整日志。',
  'errors.previous': '上一页', 'errors.next': '下一页', 'errors.image': '选择截图',
} as const
type Key = keyof typeof errorsZhCN
export const errorsZhTW: Record<Key, string> = {
  'errors.instance': '選擇實例',
  'errors.title': '故障紀錄', 'errors.hint': '查看腳本出錯時儲存的日誌與最近截圖；重新整理不會操作遊戲。',
  'errors.refresh': '重新整理紀錄', 'errors.empty': '暫無故障紀錄',
  'errors.emptyHint': '啟用「儲存錯誤日誌」後，新錯誤會自動儲存於此。已封存的舊紀錄不在此清單中。',
  'errors.disabled': '目前未啟用「儲存錯誤日誌」，新的錯誤不會儲存現場；既有紀錄仍可查看。',
  'errors.count': '共 {count} 筆', 'errors.screenshots': '{count} 張截圖', 'errors.noLog': '此現場未儲存日誌',
  'errors.log': '錯誤日誌', 'errors.images': '現場截圖', 'errors.noImages': '此現場未儲存截圖',
  'errors.downloadLog': '下載完整日誌', 'errors.downloadImage': '下載截圖', 'errors.enlarge': '放大截圖',
  'errors.truncated': '僅顯示日誌末尾 256 KiB，可下載完整日誌。',
  'errors.previous': '上一頁', 'errors.next': '下一頁', 'errors.image': '選擇截圖',
}
export const errorsEnUS: Record<Key, string> = {
  'errors.instance': 'Select instance',
  'errors.title': 'Error records', 'errors.hint': 'Inspect saved error logs and recent screenshots. Refresh does not control the game.',
  'errors.refresh': 'Refresh records', 'errors.empty': 'No error records',
  'errors.emptyHint': 'Enable “Save error logs” to save future errors here. Archived records are not listed.',
  'errors.disabled': '“Save error logs” is disabled. Future errors will not be saved; existing records remain available.',
  'errors.count': '{count} records', 'errors.screenshots': '{count} screenshots', 'errors.noLog': 'No saved log',
  'errors.log': 'Error log', 'errors.images': 'Screenshots', 'errors.noImages': 'No saved screenshots',
  'errors.downloadLog': 'Download full log', 'errors.downloadImage': 'Download screenshot', 'errors.enlarge': 'Enlarge screenshot',
  'errors.truncated': 'Showing the last 256 KiB. Download the full log to read more.',
  'errors.previous': 'Previous', 'errors.next': 'Next', 'errors.image': 'Select screenshot',
}
export const errorsJaJP: Record<Key, string> = {
  'errors.instance': 'インスタンスを選択',
  'errors.title': 'エラー記録', 'errors.hint': 'エラー時に保存したログと直近の画像を確認できます。更新してもゲームは操作されません。',
  'errors.refresh': '記録を更新', 'errors.empty': 'エラー記録はありません',
  'errors.emptyHint': '「エラーログを保存」を有効にすると、新しいエラーが保存されます。アーカイブ済みの記録は表示されません。',
  'errors.disabled': '「エラーログを保存」が無効です。新しいエラーは保存されませんが、既存の記録は確認できます。',
  'errors.count': '{count} 件', 'errors.screenshots': '画像 {count} 枚', 'errors.noLog': 'ログが保存されていません',
  'errors.log': 'エラーログ', 'errors.images': 'スクリーンショット', 'errors.noImages': '画像が保存されていません',
  'errors.downloadLog': 'ログ全体をダウンロード', 'errors.downloadImage': '画像をダウンロード', 'errors.enlarge': '画像を拡大',
  'errors.truncated': '末尾の 256 KiB を表示しています。ログ全体をダウンロードできます。',
  'errors.previous': '前へ', 'errors.next': '次へ', 'errors.image': '画像を選択',
}
export const errorsZhMiao = Object.fromEntries(Object.entries(errorsZhCN).map(([key, value]) => [key, `${value}喵`])) as Record<Key, string>
