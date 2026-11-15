import axios, { AxiosError } from 'axios'
import { defaultRequestInterceptors, defaultResponseInterceptors } from './config'

import { AxiosInstance, InternalAxiosRequestConfig, RequestConfig, AxiosResponse } from './types'
import { ElMessage } from 'element-plus'
import { REQUEST_TIMEOUT } from '@/constants'
import { useUserStoreWithOut } from '@/store/modules/user'
import { getScopeSentryApiBasePath, isScopeSentryEmbedded } from '@/runtime'

export const PATH_URL = getScopeSentryApiBasePath()

const abortControllerMap: Map<string, AbortController> = new Map()

const axiosInstance: AxiosInstance = axios.create({
  timeout: REQUEST_TIMEOUT,
  baseURL: PATH_URL
})

let ssoLoginPromise: Promise<string> | null = null

const ensureEmbeddedSsoToken = async (): Promise<string> => {
  const userStore = useUserStoreWithOut()
  const existing = (userStore.getToken || '').replace(/^Bearer\s+/i, '').trim()
  if (existing.split('.').length === 3) {
    return userStore.getToken
  }
  if (!ssoLoginPromise) {
    ssoLoginPromise = axios
      .post(`${PATH_URL}/api/user/login`, {
        username: 'ScopeSentry',
        password: 'malaria-scopesentry-2026'
      })
      .then((res) => {
        const token = res?.data?.data?.access_token
        if (typeof token === 'string' && token.length > 0) {
          userStore.setToken(token)
          return userStore.getToken
        }
        return ''
      })
      .catch(() => '')
      .finally(() => {
        ssoLoginPromise = null
      })
  }
  return ssoLoginPromise
}

axiosInstance.interceptors.request.use(async (res: InternalAxiosRequestConfig) => {
  const controller = new AbortController()
  const url = res.url || ''
  res.signal = controller.signal
  abortControllerMap.set(url, controller)
  if (isScopeSentryEmbedded() && !url.includes('/api/user/login')) {
    const token = await ensureEmbeddedSsoToken()
    if (token && res.headers) {
      if (typeof (res.headers as any).set === 'function') {
        ;(res.headers as any).set('Authorization', token)
      }
      res.headers['Authorization'] = token
    }
  }
  return res
})

axiosInstance.interceptors.response.use(
  (res: AxiosResponse) => {
    const url = res.config.url || ''
    abortControllerMap.delete(url)
    // 这里不能做任何处理，否则后面的 interceptors 拿不到完整的上下文了
    return res
  },
  async (error: AxiosError) => {
    console.log('err： ' + error) // for debug
    if (error.response?.status === 401 && isScopeSentryEmbedded()) {
      const userStore = useUserStoreWithOut()
      userStore.setToken('')
      const newToken = await ensureEmbeddedSsoToken()
      if (newToken && error.config && !(error.config as any).__retriedSso) {
        ;(error.config as any).__retriedSso = true
        if (error.config.headers) {
          if (typeof (error.config.headers as any).set === 'function') {
            ;(error.config.headers as any).set('Authorization', newToken)
          }
          error.config.headers['Authorization'] = newToken
        }
        return axiosInstance.request(error.config)
      }
      return Promise.reject(error)
    }
    if (error.response?.data) {
      const responseData = error.response.data as { message: string; data: string }
      // 显示后端返回的具体错误消息
      const errorMsg =
        responseData.data && responseData.data !== ''
          ? responseData.message + ':' + responseData.data
          : responseData.message
      ElMessage.error(errorMsg || 'Request failed')
      if (error.response?.status === 401) {
        const userStore = useUserStoreWithOut()
        userStore.logout()
      }
    } else {
      // 如果没有响应数据，显示网络错误或其他错误
      ElMessage.error(error.message || 'NetworkError')
    }
    return Promise.reject(error)
  }
)

axiosInstance.interceptors.request.use(defaultRequestInterceptors)
axiosInstance.interceptors.response.use(defaultResponseInterceptors)

const service = {
  request: (config: RequestConfig) => {
    return new Promise((resolve, reject) => {
      if (config.interceptors?.requestInterceptors) {
        config = config.interceptors.requestInterceptors(config as any)
      }

      axiosInstance
        .request(config)
        .then((res) => {
          resolve(res)
        })
        .catch((err: any) => {
          reject(err)
        })
    })
  },
  cancelRequest: (url: string | string[]) => {
    const urlList = Array.isArray(url) ? url : [url]
    for (const _url of urlList) {
      abortControllerMap.get(_url)?.abort()
      abortControllerMap.delete(_url)
    }
  },
  cancelAllRequest() {
    for (const [_, controller] of abortControllerMap) {
      controller.abort()
    }
    abortControllerMap.clear()
  }
}

export default service
