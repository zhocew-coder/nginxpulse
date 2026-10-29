package ai

import (
	"context"
	"fmt"
	"time"

	"github.com/likaia/nginxpulse/internal/store"
	"github.com/robfig/cron/v3"
	"github.com/sirupsen/logrus"
)

// Scheduler manages scheduled AI tasks
type Scheduler struct {
	cron      *cron.Cron
	db        *store.Repository
	llm       *LLMClient
	config    *Config
}

// NewScheduler creates a new AI scheduler
func NewScheduler(db *store.Repository, llm *LLMClient, config *Config) *Scheduler {
	return &Scheduler{
		cron:   cron.New(cron.WithSeconds()),
		db:     db,
		llm:    llm,
		config: config,
	}
}

// Start starts the scheduler
func (s *Scheduler) Start() {
	// Start anomaly detection scheduler
	if s.config.AnomalyDetection.Enabled {
		interval := s.config.AnomalyDetection.GetCheckInterval()
		spec := fmt.Sprintf("*/%d * * * *", int(interval.Minutes()))
		s.cron.AddFunc(spec, func() {
			logrus.Info("执行定时异常检测...")
			detector := NewAnomalyDetector(s.db, s.llm)
			reports, err := detector.DetectLastHour(context.Background())
			if err != nil {
				logrus.WithError(err).Error("异常检测失败")
				return
			}
			if len(reports) > 0 {
				logrus.Infof("检测到 %d 个异常事件", len(reports))
			}
		})
		logrus.Infof("异常检测调度已启用：%s", spec)
	}

	// Start daily report scheduler
	if s.config.Reports.Daily.Enabled && s.config.Reports.Daily.Schedule != "" {
		s.cron.AddFunc(s.config.Reports.Daily.Schedule, func() {
			logrus.Info("生成每日业务报表...")
			generator := NewReportGenerator(s.llm, s.db)
			yesterday := time.Now().AddDate(0, 0, -1)
			report, err := generator.GenerateDaily(context.Background(), yesterday, false)
			if err != nil {
				logrus.WithError(err).Error("生成每日报表失败")
				return
			}
			logrus.Infof("每日报表生成成功：PV=%v, UV=%v", report.Metrics["total_pv"], report.Metrics["total_uv"])
		})
		logrus.Infof("每日报表调度已启用：%s", s.config.Reports.Daily.Schedule)
	}

	// Start weekly report scheduler
	if s.config.Reports.Weekly.Enabled && s.config.Reports.Weekly.Schedule != "" {
		s.cron.AddFunc(s.config.Reports.Weekly.Schedule, func() {
			logrus.Info("生成每周业务报表...")
			// TODO: Implement weekly report generation
		})
		logrus.Infof("每周报表调度已启用：%s", s.config.Reports.Weekly.Schedule)
	}

	// Start monthly report scheduler
	if s.config.Reports.Monthly.Enabled && s.config.Reports.Monthly.Schedule != "" {
		s.cron.AddFunc(s.config.Reports.Monthly.Schedule, func() {
			logrus.Info("生成每月业务报表...")
			// TODO: Implement monthly report generation
		})
		logrus.Infof("每月报表调度已启用：%s", s.config.Reports.Monthly.Schedule)
	}

	s.cron.Start()
	logrus.Info("AI 调度器已启动")
}

// Stop stops the scheduler
func (s *Scheduler) Stop() {
	ctx := s.cron.Stop()
	<-ctx.Done()
	logrus.Info("AI 调度器已停止")
}
