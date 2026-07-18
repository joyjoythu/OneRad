import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import AnalysisPanel from '../AnalysisPanel.vue'
import { useAgentStore } from '@/stores/agent'

function setupWrapper() {
  return mount(AnalysisPanel, {
    global: {
      plugins: [ElementPlus],
    },
  })
}

const mockAnalysis = {
  tool_call_id: 'tc-analysis-1',
  feature_csv: 'features/radiomics.csv',
  clinical: 'clinical/data.csv',
  id_col: 'patient_id',
  label_col: 'label',
  covariates: ['age', 'gender'],
  output_dir: 'analysis_output',
  n_feature_cases: 100,
  n_features: 120,
  n_matched: 95,
  available_clinical_columns: ['patient_id', 'label', 'age', 'gender'],
}

describe('AnalysisPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders radiomics analysis summary details', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsAnalysis = mockAnalysis

    const wrapper = setupWrapper()
    const text = wrapper.text()

    expect(text).toContain('待确认影像组学分析')
    expect(text).toContain('features/radiomics.csv')
    expect(text).toContain('clinical/data.csv')
    expect(text).toContain('patient_id')
    expect(text).toContain('label')
    expect(text).toContain('95 / 120 / 4')
    expect(text).toContain('age, gender')
    expect(text).toContain('analysis_output')
  })

  it('renders no action buttons (read-only display)', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsAnalysis = mockAnalysis

    const wrapper = setupWrapper()

    expect(wrapper.findAll('button')).toHaveLength(0)
  })
})
