<script setup>
// The live phone shown while a post is being written: renders the streaming draft (liveDraft.js) with the
// same skins as the server-rendered preview, so the text types straight into the phone. Images are loaded
// by index from /api/stream-image (no media ids in the browser); a missing one is simply left out.
import { computed, ref } from 'vue'
import { sessionId } from '../api.js'

const props = defineProps({ live: { type: Object, required: true }, scope: { type: String, default: 'manual' } })

const post = computed(() => props.live.post || {})
const platform = computed(() => props.live.platform || 'xiaohongshu')
const skin = computed(() => ({ wechat_article: 'wechat', xiaohongshu: 'xhs', moments: 'moments', poster: 'poster' }[platform.value] || 'douyin'))
const failed = ref({})

const images = computed(() => (props.live.images || []).filter((im) => !failed.value[im.idx]))
const byPosition = computed(() => {
  const m = {}
  for (const im of images.value) (m[im.position] = m[im.position] || []).push(im)
  return m
})
function imgsAfter(k) { return byPosition.value[`第${k + 1}段后`] || [] }
function src(im) {
  return `/api/stream-image?scope=${props.scope}&session_id=${encodeURIComponent(sessionId.value)}&idx=${im.idx}`
}
function onImgError(im) { failed.value = { ...failed.value, [im.idx]: true } }
</script>

<template>
  <div class="hw-phone" :class="'skin-' + skin">
    <div class="notch"></div>
    <div class="screen">
      <!-- 公众号 -->
      <template v-if="platform === 'wechat_article'">
        <div class="topbar"><span>‹</span><span>公众号</span><span>···</span></div>
        <h2>{{ post.title }}</h2>
        <div class="meta">华为门店 · 刚刚</div>
        <div class="body">
          <template v-for="im in (byPosition['标题下方'] || [])" :key="im.idx">
            <img :src="src(im)" alt="" @error="onImgError(im)" /><div class="cap">{{ im.caption }}</div>
          </template>
          <div class="p">{{ post.intro }}</div>
          <template v-for="(b, k) in post.body" :key="k">
            <div class="p">{{ b }}</div>
            <template v-for="im in imgsAfter(k)" :key="im.idx">
              <img :src="src(im)" alt="" @error="onImgError(im)" /><div class="cap">{{ im.caption }}</div>
            </template>
          </template>
          <template v-for="im in images.filter((i) => i.position !== '标题下方' && !/^第\d+段后$/.test(i.position))" :key="im.idx">
            <img :src="src(im)" alt="" @error="onImgError(im)" /><div class="cap">{{ im.caption }}</div>
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
              <img v-for="im in images" :key="im.idx" :src="src(im)" alt="" @error="onImgError(im)" />
            </div>
            <div class="cta">{{ post.cta }}</div>
            <div class="time">刚刚</div>
          </div>
        </div>
      </template>

      <!-- 海报 -->
      <template v-else-if="platform === 'poster'">
        <img v-if="images[0]" :src="src(images[0])" alt="" @error="onImgError(images[0])" />
        <h2>{{ post.title }}</h2>
        <div class="sub">{{ post.intro }}</div>
        <div v-for="(b, k) in post.body" :key="k" class="pt">{{ b }}</div>
        <div class="cta">{{ post.cta }}</div>
      </template>

      <!-- 抖音 -->
      <template v-else-if="platform === 'douyin'">
        <div class="gallery"><img v-for="im in images" :key="im.idx" :src="src(im)" alt="" @error="onImgError(im)" /></div>
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
        <div class="gallery"><img v-for="im in images" :key="im.idx" :src="src(im)" alt="" @error="onImgError(im)" /></div>
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
