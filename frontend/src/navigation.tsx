import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from 'react'

function subscribe(listener: () => void) {
  window.addEventListener('popstate', listener)
  return () => window.removeEventListener('popstate', listener)
}
export function useLocation() {
  return useSyncExternalStore(subscribe, () => window.location.pathname + window.location.search)
}
export function navigate(path: string) {
  window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}
export function Link({
  href,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  function visit(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return
    event.preventDefault()
    navigate(href)
  }
  return <a href={href} {...props} onClick={visit} />
}
