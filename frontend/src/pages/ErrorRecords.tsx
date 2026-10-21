import {useEffect, useState} from 'react'
import {Link, Navigate, useParams, useSearchParams} from 'react-router-dom'
import {Bug, Download, Maximize2, RefreshCw} from 'lucide-react'
import {api} from '../api/client'
import type {ErrorDetail, ErrorList} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {Select} from '../components/FormControls'
import {Empty, ErrorBox, Loading, Modal, PageTitle} from '../components/ui'
import '../errors/errors.css'

const PAGE_SIZE = 30

export function ErrorRecords() {
  const {instance: legacyInstance} = useParams()
  const [params, setParams] = useSearchParams()
  const {instances, instancesLoaded, ui} = useApp()
  const instance = instances.find(item => item.name === params.get('instance'))?.name ?? instances[0]?.name
  if (legacyInstance) return <Navigate to={`/errors?instance=${encodeURIComponent(legacyInstance)}`} replace/>
  if (!instancesLoaded) return <Loading/>
  if (!instance) return <div className="error-records"><PageTitle title={ui('errors.title')}/><Empty icon={<Bug size={36}/>} title={ui('instance.createFirst')}><Link to="/configs">{ui('nav.configs')}</Link></Empty></div>
  // 切换实例时销毁旧请求和选中状态，防止把上一实例的现场显示到新实例。
  return <Records key={instance} instance={instance} onInstanceChange={name => setParams({instance: name})}/>
}

function Records({instance, onInstanceChange}: {instance: string; onInstanceChange: (name: string) => void}) {
  const {ui, language, instances} = useApp(), connection = useConnection()
  const [list, setList] = useState<ErrorList>(), [selected, setSelected] = useState('')
  const [detail, setDetail] = useState<ErrorDetail>(), [imageName, setImageName] = useState('')
  const [image, setImage] = useState(''), [imageLoading, setImageLoading] = useState(false)
  const [error, setError] = useState(''), [detailError, setDetailError] = useState(''), [imageError, setImageError] = useState('')
  const [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(false)
  const [enlarged, setEnlarged] = useState(false), [downloading, setDownloading] = useState(false)
  const ready = connection === 'ready'
  const date = (timestamp: number) => new Date(timestamp).toLocaleString(language === 'zh-MIAO' ? 'zh-CN' : language, {hour12: false})

  useEffect(() => {
    if (!ready) return
    let active = true
    setLoading(true); setError('')
    void api.request('errors.list', {instance, offset, limit: PAGE_SIZE}).then(result => {
      if (!active) return
      // 清理导致当前页消失时回到第一页。
      if (offset && offset >= result.total) { setOffset(0); return }
      setList(result)
      setSelected(current => result.entries.some(entry => entry.id === current) ? current : result.entries[0]?.id ?? '')
    }).catch(error => { if (active) setError((error as Error).message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [instance, ready, offset, refresh])

  useEffect(() => {
    setDetail(undefined); setDetailError(''); setImageName(''); setEnlarged(false)
    if (!ready || !selected) return
    let active = true
    void api.request('errors.detail', {instance, record: selected}).then(result => {
      if (active) { setDetail(result); setImageName(result.images.at(-1) ?? '') }
    }).catch(error => { if (active) setDetailError((error as Error).message) })
    return () => { active = false }
  }, [instance, ready, selected, refresh])

  useEffect(() => {
    setImage(''); setImageError(''); setImageLoading(false); setEnlarged(false)
    if (!ready || !detail || detail.id !== selected || !imageName) return
    let active = true
    setImageLoading(true)
    void api.request('errors.file', {instance, record: selected, name: imageName}).then(result => {
      if (active) setImage(`data:${result.media_type};base64,${result.content}`)
    }).catch(error => { if (active) setImageError((error as Error).message) })
      .finally(() => { if (active) setImageLoading(false) })
    return () => { active = false }
  }, [instance, ready, selected, detail, imageName])

  async function downloadLog() {
    setDownloading(true); setDetailError('')
    try {
      const file = await api.request('errors.file', {instance, record: selected, name: 'log.txt'})
      const url = URL.createObjectURL(new Blob([Uint8Array.from(atob(file.content), char => char.charCodeAt(0))], {type: file.media_type}))
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = `${instance}-${selected}-log.txt`; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { setDetailError((error as Error).message) } finally { setDownloading(false) }
  }

  return <div className="error-records">
    <PageTitle title={ui('errors.title')} actions={<button className="button secondary" disabled={!ready || loading} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={16}/>{ui('errors.refresh')}</button>}/>
    <p className="muted">{ui('errors.hint')}</p>
    <label className="error-record-instance-select">{ui('errors.instance')}<Select value={instance} onChange={event => onInstanceChange(event.target.value)}>{instances.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</Select></label>
    {list && !list.enabled && <p className="error-record-notice" role="status">{ui('errors.disabled')}</p>}
    {error && <ErrorBox message={error}/>}
    {!list && !error && <Loading/>}
    {list && list.entries.length === 0 && <Empty icon={<Bug size={36}/>} title={ui('errors.empty')}>{ui('errors.emptyHint')}</Empty>}
    {list && list.entries.length > 0 && <div className="error-record-layout">
      <section className="panel error-record-list" aria-label={ui('errors.title')} aria-busy={loading}>
        <h2>{ui('errors.count', {count: list.total})}</h2>
        {list.entries.map(entry => <button key={entry.id} className="error-record-item" aria-pressed={selected === entry.id} onClick={() => setSelected(entry.id)}>
          <time dateTime={new Date(entry.timestamp).toISOString()}>{date(entry.timestamp)}</time>
          <small>{ui('errors.screenshots', {count: entry.screenshots})}{!entry.has_log && ` · ${ui('errors.noLog')}`}</small>
        </button>)}
        <div className="error-record-pagination"><button className="button secondary" disabled={!ready || loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>{ui('errors.previous')}</button>
          <button className="button secondary" disabled={!ready || loading || offset + PAGE_SIZE >= list.total} onClick={() => setOffset(value => value + PAGE_SIZE)}>{ui('errors.next')}</button></div>
      </section>
      <div className="error-record-detail">
        {detailError && <ErrorBox message={detailError}/>}
        {!detail && !detailError && <Loading/>}
        {detail && <>
          <section className="panel error-record-images" aria-label={ui('errors.images')}>
            <div className="panel-heading"><h2>{ui('errors.images')}</h2><span className="muted">{date(Number(detail.id))}</span></div>
            {detail.images.length ? <>
              <label className="error-record-image-select">{ui('errors.image')}<Select value={imageName} onChange={event => setImageName(event.target.value)}>{detail.images.map((name, index) => <option key={name} value={name}>{index + 1} / {detail.images.length} · {name.replace('.png', '')}</option>)}</Select></label>
              {imageError && <ErrorBox message={imageError}/>}
              {imageLoading && <Loading/>}
              {image && <><button className="error-record-preview" aria-label={ui('errors.enlarge')} onClick={() => setEnlarged(true)}><img src={image} alt={imageName}/><span><Maximize2 size={16}/>{ui('errors.enlarge')}</span></button>
                <a className="button secondary" href={image} download={`${instance}-${selected}-${imageName}`}><Download size={16}/>{ui('errors.downloadImage')}</a></>}
            </> : <p className="muted">{ui('errors.noImages')}</p>}
          </section>
          <section className="panel error-record-log" aria-label={ui('errors.log')}>
            <div className="panel-heading"><h2>{ui('errors.log')}</h2>{detail.log !== null && <button className="button secondary" disabled={!ready || downloading} onClick={downloadLog}><Download size={16}/>{ui('errors.downloadLog')}</button>}</div>
            {detail.truncated && <p className="error-record-notice">{ui('errors.truncated')}</p>}
            {detail.log === null ? <p className="muted">{ui('errors.noLog')}</p> : <pre tabIndex={0}>{detail.log}</pre>}
          </section>
        </>}
      </div>
    </div>}
    {enlarged && image && <Modal title={imageName} className="error-record-modal" onClose={() => setEnlarged(false)}><img src={image} alt={imageName}/></Modal>}
  </div>
}
