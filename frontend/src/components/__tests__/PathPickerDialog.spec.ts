import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import PathPickerDialog from '../PathPickerDialog.vue'

vi.mock('@/api/filesystem', () => ({
  listFilesystemRoots: vi.fn(),
  listFilesystemEntries: vi.fn(),
}))

import * as filesystemApi from '@/api/filesystem'

const wrappers: Array<{ unmount: () => void }> = []

function mountPicker(props: Record<string, unknown> = {}) {
  const wrapper = mount(PathPickerDialog, {
    attachTo: document.body,
    props: {
      visible: true,
      ...props,
    },
    global: { plugins: [ElementPlus] },
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('PathPickerDialog', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(filesystemApi.listFilesystemRoots).mockResolvedValue([
      { name: '本地磁盘 (C:)', path: 'C:\\' },
    ])
  })

  afterEach(() => {
    wrappers.forEach((wrapper) => wrapper.unmount())
    wrappers.length = 0
  })

  it('navigates directories and returns the current directory', async () => {
    vi.mocked(filesystemApi.listFilesystemEntries)
      .mockResolvedValueOnce({
        path: 'C:\\',
        parent: null,
        breadcrumbs: [{ name: 'C:\\', path: 'C:\\' }],
        entries: [{ name: 'study', path: 'C:\\study', is_dir: true }],
      })
      .mockResolvedValueOnce({
        path: 'C:\\study',
        parent: 'C:\\',
        breadcrumbs: [
          { name: 'C:\\', path: 'C:\\' },
          { name: 'study', path: 'C:\\study' },
        ],
        entries: [],
      })

    const wrapper = mountPicker({ mode: 'directory' })
    await flushPromises()

    const directory = document.querySelector<HTMLElement>('[data-testid="path-picker-directory"]')
    expect(directory).toBeTruthy()
    directory!.click()
    await flushPromises()

    document.querySelector<HTMLElement>('[data-testid="path-picker-confirm"]')!.click()
    await flushPromises()

    expect(filesystemApi.listFilesystemEntries).toHaveBeenNthCalledWith(2, 'C:\\study')
    const directorySelections = wrapper.emitted('select') ?? []
    expect(directorySelections[directorySelections.length - 1]).toEqual(['C:\\study'])
  })

  it('only allows configured clinical file extensions', async () => {
    vi.mocked(filesystemApi.listFilesystemEntries).mockResolvedValue({
      path: 'C:\\data',
      parent: 'C:\\',
      breadcrumbs: [{ name: 'data', path: 'C:\\data' }],
      entries: [
        { name: 'clinical.xlsx', path: 'C:\\data\\clinical.xlsx', is_dir: false },
        { name: 'notes.txt', path: 'C:\\data\\notes.txt', is_dir: false },
      ],
    })

    const wrapper = mountPicker({
      mode: 'file',
      modelValue: 'C:\\data',
      acceptedExtensions: ['.csv', '.xlsx', '.xls'],
    })
    await flushPromises()

    const files = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[data-testid="path-picker-file"]')
    )
    expect(files).toHaveLength(2)
    expect(files[0].disabled).toBe(false)
    expect(files[1].disabled).toBe(true)

    files[0].click()
    await flushPromises()
    document.querySelector<HTMLElement>('[data-testid="path-picker-confirm"]')!.click()
    await flushPromises()

    const fileSelections = wrapper.emitted('select') ?? []
    expect(fileSelections[fileSelections.length - 1]).toEqual(['C:\\data\\clinical.xlsx'])
  })

  it('keeps the browser usable after a listing failure and retries', async () => {
    vi.mocked(filesystemApi.listFilesystemEntries)
      .mockRejectedValueOnce(new Error('目录暂时不可用'))
      .mockResolvedValueOnce({
        path: 'C:\\',
        parent: null,
        breadcrumbs: [],
        entries: [],
      })

    mountPicker()
    await flushPromises()

    expect(document.body.textContent).toContain('目录暂时不可用')
    document.querySelector<HTMLElement>('[data-testid="path-picker-retry"]')!.click()
    await flushPromises()

    expect(filesystemApi.listFilesystemEntries).toHaveBeenCalledTimes(2)
    expect(document.body.textContent).not.toContain('目录暂时不可用')
  })
})
