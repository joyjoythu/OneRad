<template>
  <div class="agent-avatar" role="img" aria-label="智能体头像">
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <line
        x1="7.5"
        y1="9.5"
        x2="7.5"
        y2="14.5"
        style="stroke: var(--app-accent-text)"
        stroke-width="3.4"
        stroke-linecap="round"
      />
      <line
        x1="16.5"
        y1="9.5"
        x2="16.5"
        y2="14.5"
        style="stroke: var(--app-accent-text)"
        stroke-width="3.4"
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
  background-color: var(--app-accent);
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
