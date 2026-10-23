<script setup>
// 开始页 (signed out): an editorial split-screen landing — the oversized slogan on the left, the login
// entry on the right. 登录 opens the existing login page; authentication is untouched.
import { ArrowRight } from 'lucide-vue-next'

const emit = defineEmits(['go'])
</script>

<template>
  <div id="main" class="landing" tabindex="-1">
    <section class="landing-hero">
      <h1 class="landing-slogan">
        <span>把今天的</span><em>推荐</em><span>，</span><br /><span class="line-2">做成明天的<em>爆款</em>！</span>
      </h1>
    </section>

    <section class="landing-panel" aria-label="登录">
      <div class="landing-panel-inner">
        <img class="landing-logo landing-logo-sm" src="/logo.png" alt="HUAWEI" />
        <div class="landing-panel-name">PC 软文助手</div>
        <p class="landing-panel-sub">选择门店与身份，登录后开始今天的推荐。</p>
        <button class="btn btn-dark btn-lg" @click="emit('go', 'login')">登录<ArrowRight :size="18" aria-hidden="true" /></button>
      </div>
    </section>
  </div>
</template>
