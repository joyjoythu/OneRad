import axios from 'axios'
import { ElMessage } from 'element-plus'

export const API_BASE = '/api'

const client = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

export default client
