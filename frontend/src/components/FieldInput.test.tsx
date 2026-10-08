import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { FieldInput } from './FieldInput'

describe('配置输入控件', () => {
  it('显式文本模式不会被旧的数字配置值改回数字输入框', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={{ui: (key, params) => translateUi('zh-CN', key, params)} as AppContextValue}>
        <FieldInput id="target-zone" label="指定海域" type="input" mode="text" value={12} onChange={vi.fn()}/>
      </AppContext.Provider>,
    )

    expect(html).toContain('type="text"')
    expect(html).not.toContain('inputMode="decimal"')
  })

  it('关卡候选同时提供文本框和下拉，手填值不在候选中时下拉显示占位', () => {
    const render = (value: string) => renderToStaticMarkup(
      <AppContext.Provider value={{ui: (key, params) => translateUi('zh-CN', key, params)} as AppContextValue}>
        <FieldInput id="Event.Campaign.Name" label="关卡名称" type="input" value={value} suggestions={['A1', 'B1', 'SP']} onChange={vi.fn()}/>
      </AppContext.Provider>,
    )
    const custom = render('D3_3')
    expect(custom).toContain('combo-control')
    expect(custom).toContain('value="D3_3"')
    expect(custom).toContain('选择关卡')
    expect(custom).toContain('<option value="&quot;SP&quot;">SP</option>')

    const picked = render('b1')
    expect(picked).toMatch(/<option value="&quot;B1&quot;" selected="">B1<\/option>/)
  })

  it('没有候选时保持普通文本框', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={{ui: (key, params) => translateUi('zh-CN', key, params)} as AppContextValue}>
        <FieldInput id="Main.Campaign.Name" label="关卡名称" type="input" value="7-2" suggestions={[]} onChange={vi.fn()}/>
      </AppContext.Provider>,
    )
    expect(html).not.toContain('combo-control')
  })
})
