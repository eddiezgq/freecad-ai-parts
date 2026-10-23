<!-- 生产成本（第 30 轮）：企业工厂没有“经营与财务”（只在演示工厂开），厂长在这里看设备综合效率、本月交付、工单成本分解。
     内容就是“经营与财务 → 生产与成本”标签里的同一个组件 -->
<template>
  <div class="page">
    <div class="page-title"><h1>生产成本</h1>
      <span class="muted">设备综合效率 · 本月交付 · 工单成本分解（工时 × 工作站每小时费率）</span></div>
    <ProductionCost data-help="cost-production" />
  </div>
</template>

<script setup>
import ProductionCost from '../components/ProductionCost.vue';
</script>
