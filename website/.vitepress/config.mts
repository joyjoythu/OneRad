import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  base: '/OneRad/',
  lang: 'zh-CN',
  title: 'OneRad 使用指南',
  description: 'OneRad — 自然语言驱动的影像组学智能体 · 使用指南',
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: [/^https?:\/\/localhost(:\d+)?/],

  head: [
    ['meta', { name: 'theme-color', content: '#3c6df0' }],
  ],

  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    siteTitle: 'OneRad 使用指南',

    nav: [
      { text: '首页', link: '/' },
      { text: '快速上手', link: '/guide/installation' },
      { text: '功能详解', link: '/features/human-approval' },
      { text: '参考', link: '/reference/yaml-config' },
    ],

    sidebar: [
      {
        text: '快速上手',
        items: [
          { text: '安装部署', link: '/guide/installation' },
          { text: '5 分钟快速上手', link: '/guide/quickstart' },
          { text: '数据准备', link: '/guide/data-preparation' },
          { text: '完整分析流程', link: '/guide/workflow' },
        ],
      },
      {
        text: '功能详解',
        items: [
          { text: '审批面板与人机协同', link: '/features/human-approval' },
          { text: '并行子 Agent 探索', link: '/features/subagents' },
          { text: '@ 文件索引', link: '/features/file-index' },
          { text: '项目记忆', link: '/features/project-memory' },
          { text: '断点续提', link: '/features/resume' },
          { text: 'Word 统计报告', link: '/features/word-report' },
        ],
      },
      {
        text: '参考',
        items: [
          { text: 'PyRadiomics 参数配置', link: '/reference/yaml-config' },
          { text: '常见问题 FAQ', link: '/reference/faq' },
        ],
      },
    ],

    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            noResultsText: '未找到相关结果',
            resetButtonTitle: '清除查询',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
      },
    },

    outline: { label: '本页目录', level: [2, 3] },
    docFooter: { prev: '上一篇', next: '下一篇' },
    lastUpdated: { text: '最近更新' },
    returnToTopLabel: '回到顶部',
    sidebarMenuLabel: '菜单',
    darkModeSwitchLabel: '主题',
    lightModeSwitchTitle: '切换到浅色模式',
    darkModeSwitchTitle: '切换到深色模式',

    editLink: {
      pattern: 'https://github.com/joyjoythu/OneRad/edit/master/website/:path',
      text: '在 GitHub 上编辑此页',
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/joyjoythu/OneRad' },
    ],

    footer: {
      message: '基于 VitePress 构建',
      copyright: 'OneRad · AutoRadiomic Agent',
    },
  },
})
