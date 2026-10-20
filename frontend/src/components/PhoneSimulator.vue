<script setup>
import { computed } from 'vue'

const props = defineProps({ result: Object })

const post = computed(() => props.result?.post || {})
const images = computed(() => props.result?.images || [])
const platform = computed(() => props.result?.platform || 'xiaohongshu')

const byPosition = computed(() => {
  const m = {}
  for (const im of images.value) (m[im.position] = m[im.position] || []).push(im)
  return m
})

function imgsAfter(k) {
  return byPosition.value[`第${k + 1}段后`] || []
}
</script>

<template>
  <div class="hw-phone" :class="'skin-' + (platform === 'wechat_article' ? 'wechat' : platform === 'xiaohongshu' ? 'xhs' : platform === 'moments' ? 'moments' : platform === 'poster' ? 'poster' : 'douyin')">
    <div class="notch"></div>
    <div class="screen">
      <!-- 公众号 -->
      <template v-if="platform === 'wechat_article'">
        <div class="topbar"><span>‹</span><span>公众号</span><span>···</span></div>
        <h2>{{ post.title }}</h2>
        <div class="meta">华为门店 · 刚刚</div>
        <div class="body">
          <template v-for="im in (byPosition['标题下方'] || [])" :key="im.media_id">
            <img :src="im.url" :alt="im.title" /><div class="cap">{{ im.caption }}</div>
          </template>
          <div class="p">{{ post.intro }}</div>
          <template v-for="(b, k) in post.body" :key="k">
            <div class="p">{{ b }}</div>
            <template v-for="im in imgsAfter(k)" :key="im.media_id">
              <img :src="im.url" :alt="im.title" /><div class="cap">{{ im.caption }}</div>
            </template>
          </template>
          <template v-for="im in images.filter(i => i.position !== '标题下方' && !/^第\d+段后$/.test(i.position))" :key="im.media_id">
            <img :src="im.url" :alt="im.title" /><div class="cap">{{ im.caption }}</div>
          </template>
          <div class="cta">{{ post.cta }}</div>
        </div>
      </template>

      <!-- 朋友圈 -->
      <template v-else-if="platform === 'moments'">
        <div class="topbar"><span>‹</span><span>朋友圈</span><span>📷</span></div>
        <div class="post">
          <div class="avatar"></div>
          <div style="flex:1">
            <div class="name">华为授权体验店</div>
            <div v-for="(b, k) in post.body" :key="k" class="p">{{ b }}</div>
            <div class="grid" :class="{ one: images.length === 1 }">
              <img v-for="im in images" :key="im.media_id" :src="im.url" :alt="im.title" />
            </div>
            <div class="cta">{{ post.cta }}</div>
            <div class="time">刚刚</div>
          </div>
        </div>
      </template>

      <!-- 海报 -->
      <template v-else-if="platform === 'poster'">
        <img v-if="images[0]" :src="images[0].url" :alt="images[0].title" />
        <h2>{{ post.title }}</h2>
        <div class="sub">{{ post.intro }}</div>
        <div v-for="(b, k) in post.body" :key="k" class="pt">{{ b }}</div>
        <div class="cta">{{ post.cta }}</div>
      </template>

      <!-- 抖音 -->
      <template v-else-if="platform === 'douyin'">
        <div class="gallery"><img v-for="im in images" :key="im.media_id" :src="im.url" :alt="im.title" /></div>
        <div class="body">
          <b>{{ post.title }}</b>
          <div class="p">{{ post.intro }}</div>
          <div v-for="(b, k) in post.body" :key="k" class="p">{{ b }}</div>
          <div class="cta">{{ post.cta }}</div>
          <div class="tags"><span v-for="t in post.tags" :key="t">#{{ t }}</span></div>
        </div>
      </template>

      <!-- 小红书 -->
      <template v-else>
        <div class="author"><div class="avatar"></div><span>华为门店小助手</span></div>
        <div class="gallery"><img v-for="im in images" :key="im.media_id" :src="im.url" :alt="im.title" /></div>
        <h2>{{ post.title }}</h2>
        <div class="body">
          <div class="p">{{ post.intro }}</div>
          <div v-for="(b, k) in post.body" :key="k" class="p">{{ b }}</div>
          <div class="cta">{{ post.cta }}</div>
          <div class="tags"><span v-for="t in post.tags" :key="t">#{{ t }}</span></div>
        </div>
      </template>
    </div>
  </div>
</template>
