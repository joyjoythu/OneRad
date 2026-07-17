<template>
  <div class="agent-avatar" role="img" aria-label="智能体头像">
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <line x1="12" y1="7" x2="12" y2="4.5" stroke="#ffffff" stroke-width="1.5" />
      <circle cx="12" cy="3.5" r="1.2" fill="#ffffff" />
      <rect x="4" y="7" width="16" height="12.5" rx="3.5" fill="#ffffff" />
      <circle cx="9.3" cy="12.5" r="1.5" fill="#409eff" />
      <circle cx="14.7" cy="12.5" r="1.5" fill="#409eff" />
      <line
        x1="9"
        y1="16.3"
        x2="15"
        y2="16.3"
        stroke="#409eff"
        stroke-width="1.5"
        stroke-linecap="round"
      />
    </svg>
  </div>
</template>

<style scoped>
.agent-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: #409eff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-avatar svg {
  width: 22px;
  height: 22px;
}
</style>
