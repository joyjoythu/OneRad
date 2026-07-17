import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import SettingsView from '../SettingsView.vue'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/api/projects'

const mockProject = (): Project => ({
  id: 'proj-1',
  name: '测试项目',
  path: '/tmp/proj-1',
  description: '',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  analysis: {
    image_dir: 'images',
    clinical_path: 'clinical.xlsx',
    output_dir: './outputs',
    modality: 'auto',
    covariates: 'age',
    model: 'logistic',
    analysis_model: 'logistic',
    api_key: 'sk-old',
  },
})

function setupWrapper() {
  return mount(SettingsView, {
    global: { plugins: [ElementPlus] },
  })
}

describe('SettingsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('prompts to select a project when none is selected', () => {
    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('请先选择一个项目')
  })

  it('renders the api key input initialized from currentConfig', () => {
    const store = useProjectStore()
    store.currentProject = mockProject()
    store.currentConfig = { ...mockProject().analysis }

    const wrapper = setupWrapper()

    const input = wrapper.find('input')
    expect((input.element as HTMLInputElement).value).toBe('sk-old')
  })

  it('saves only the api key while keeping other config fields', async () => {
    const store = useProjectStore()
    const project = mockProject()
    store.currentProject = project
    store.currentConfig = { ...project.analysis }
    const saveSpy = vi.spyOn(store, 'saveConfig').mockResolvedValue(project)

    const wrapper = setupWrapper()
    await wrapper.find('input').setValue('sk-new')
    await wrapper.find('[data-testid="settings-save"]').trigger('click')
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledWith('proj-1', {
      ...project.analysis,
      api_key: 'sk-new',
    })
  })
})
